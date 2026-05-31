from __future__ import annotations

import re
import shutil
import subprocess
import time
from .models import CleanupResult, TestCase


class CleanupManager:
    def __init__(self, logger=None):
        self.logger = logger

    def cleanup_for_test(self, test: TestCase, cwd: str | None = None) -> list[CleanupResult]:
        cleanup_specs = self._commands_for_test(test)
        results: list[CleanupResult] = []
        for command, verifier in cleanup_specs:
            if self.logger:
                self.logger.info("cleanup command: %s", command)
            started = time.time()
            proc = subprocess.run(command, shell=True, cwd=cwd, text=True, capture_output=True, check=False, timeout=30)
            verified, message = verifier() if verifier else (proc.returncode == 0, "cleanup command completed")
            results.append(CleanupResult(command, proc.returncode, verified, message, time.time() - started))
        return results

    def _commands_for_test(self, test: TestCase):
        cmd = test.command_block
        commands = []
        for name in sorted(set(re.findall(r"(?:--name\s+|--name=)([\w.-]+)", cmd))):
            commands.append((f"docker rm -f {self._q(name)} >/dev/null 2>&1 || true", lambda n=name: (not self._docker_exists("container", n), f"container {n} removed")))
        for name in sorted(set(re.findall(r"docker\s+network\s+create(?:\s+\S+)*\s+([\w.-]+)\s*$", cmd, re.I | re.M))):
            if name not in {"bridge", "host", "none"}:
                commands.append((f"docker network rm {self._q(name)} >/dev/null 2>&1 || true", lambda n=name: (not self._docker_exists("network", n), f"network {n} removed")))
        for name in sorted(set(re.findall(r"docker\s+volume\s+create(?:\s+\S+)*\s+([\w.-]+)\s*$", cmd, re.I | re.M))):
            commands.append((f"docker volume rm {self._q(name)} >/dev/null 2>&1 || true", lambda n=name: (not self._docker_exists("volume", n), f"volume {n} removed")))
        for name in sorted(set(re.findall(r"\bip\s+netns\s+add\s+([\w.-]+)", cmd, re.I))):
            commands.append((f"ip netns delete {self._q(name)} >/dev/null 2>&1 || true", lambda n=name: (not self._netns_exists(n), f"namespace {n} removed")))
        for name in sorted(set(re.findall(r"docker\s+service\s+create[\s\S]*?(?:--name\s+|--name=)([\w.-]+)", cmd, re.I))):
            commands.append((f"docker service rm {self._q(name)} >/dev/null 2>&1 || true", lambda n=name: (not self._docker_service_exists(n), f"service {n} removed")))
        if re.search(r"docker(?:-compose|\s+compose)[\s\S]*\bup\b", cmd, re.I):
            commands.append(("docker compose down -v --remove-orphans >/dev/null 2>&1 || docker-compose down -v --remove-orphans >/dev/null 2>&1 || true", lambda: (True, "compose down executed")))
        for path in sorted(set(re.findall(r"(?:mktemp\s+-d|TMPDIR=)(?:\s+)?([/\w.-]+)", cmd))):
            if path.startswith("/tmp/"):
                commands.append((f"rm -rf {self._q(path)}", lambda p=path: (True, f"temporary path {p} removed")))
        return commands

    def cleanup_all_known(self) -> None:
        if shutil.which("docker") is None:
            return
        subprocess.run("docker container prune -f --filter label=docker-lab-validator=true >/dev/null 2>&1 || true", shell=True, check=False)
        subprocess.run("docker network prune -f --filter label=docker-lab-validator=true >/dev/null 2>&1 || true", shell=True, check=False)
        subprocess.run("docker volume prune -f --filter label=docker-lab-validator=true >/dev/null 2>&1 || true", shell=True, check=False)

    def _docker_exists(self, kind: str, name: str) -> bool:
        result = subprocess.run(["docker", kind, "inspect", name], text=True, capture_output=True, check=False, timeout=10)
        return result.returncode == 0

    def _docker_service_exists(self, name: str) -> bool:
        result = subprocess.run(["docker", "service", "inspect", name], text=True, capture_output=True, check=False, timeout=10)
        return result.returncode == 0

    def _netns_exists(self, name: str) -> bool:
        result = subprocess.run(["ip", "netns", "list"], text=True, capture_output=True, check=False, timeout=10)
        return result.returncode == 0 and any(line.split()[0] == name for line in result.stdout.splitlines() if line.strip())

    def _q(self, value: str) -> str:
        return "'" + value.replace("'", "'\\''") + "'"
