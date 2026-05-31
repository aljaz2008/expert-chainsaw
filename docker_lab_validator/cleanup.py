from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from .models import TestCase


class CleanupManager:
    def __init__(self, logger=None):
        self.logger = logger

    def cleanup_for_test(self, test: TestCase, cwd: str | None = None) -> list[str]:
        commands = self._commands_for_test(test)
        executed: list[str] = []
        for command in commands:
            executed.append(command)
            if self.logger:
                self.logger.info("cleanup command: %s", command)
            subprocess.run(command, shell=True, cwd=cwd, text=True, capture_output=True, check=False, timeout=30)
        return executed

    def _commands_for_test(self, test: TestCase) -> list[str]:
        cmd = test.command_block
        commands: list[str] = []
        for name in sorted(set(re.findall(r"(?:--name\s+|--name=)([\w.-]+)", cmd))):
            commands.append(f"docker rm -f {self._q(name)} >/dev/null 2>&1 || true")
        for name in sorted(set(re.findall(r"docker\s+network\s+create(?:\s+\S+)*\s+([\w.-]+)\s*$", cmd, re.I | re.M))):
            if name not in {"bridge", "host", "none"}:
                commands.append(f"docker network rm {self._q(name)} >/dev/null 2>&1 || true")
        for name in sorted(set(re.findall(r"docker\s+volume\s+create(?:\s+\S+)*\s+([\w.-]+)\s*$", cmd, re.I | re.M))):
            commands.append(f"docker volume rm {self._q(name)} >/dev/null 2>&1 || true")
        if re.search(r"docker(?:-compose|\s+compose)[\s\S]*\bup\b", cmd, re.I):
            commands.append("docker compose down -v --remove-orphans >/dev/null 2>&1 || docker-compose down -v --remove-orphans >/dev/null 2>&1 || true")
        for path in sorted(set(re.findall(r"(?:mktemp\s+-d|TMPDIR=)(?:\s+)?([/\w.-]+)", cmd))):
            if path.startswith("/tmp/"):
                commands.append(f"rm -rf {self._q(path)}")
        return commands

    def cleanup_all_known(self) -> None:
        if shutil.which("docker") is None:
            return
        subprocess.run("docker container prune -f --filter label=docker-lab-validator=true >/dev/null 2>&1 || true", shell=True, check=False)
        subprocess.run("docker network prune -f --filter label=docker-lab-validator=true >/dev/null 2>&1 || true", shell=True, check=False)
        subprocess.run("docker volume prune -f --filter label=docker-lab-validator=true >/dev/null 2>&1 || true", shell=True, check=False)

    def _q(self, value: str) -> str:
        return "'" + value.replace("'", "'\\''") + "'"
