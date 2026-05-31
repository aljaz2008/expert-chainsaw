from __future__ import annotations

import re
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Iterable
from .models import AssertionResult, CommandExecution, TestCase, TestStatus
from .platform import PlatformInfo


@dataclass(frozen=True)
class ResourceExpectation:
    kind: str
    name: str
    should_exist: bool
    assertion: str


class DockerAssertionEngine:
    """Infers and evaluates semantic assertions for Docker/networking commands."""

    def infer_expectations(self, test: TestCase) -> list[ResourceExpectation]:
        cmd = test.command_block
        expectations: list[ResourceExpectation] = []
        for name in re.findall(r"docker\s+network\s+create(?:\s+--[\w-]+(?:[= ]\S+)?)?\s+([\w.-]+)", cmd, re.I):
            expectations.append(ResourceExpectation("network", name, True, "network_exists"))
        for name in re.findall(r"docker\s+network\s+rm\s+([\w.-]+)", cmd, re.I):
            expectations.append(ResourceExpectation("network", name, False, "network_removed"))
        for name in re.findall(r"docker\s+(?:container\s+)?run[\s\S]*?(?:--name\s+|--name=)([\w.-]+)", cmd, re.I):
            detached = bool(re.search(r"docker\s+(?:container\s+)?run[\s\S]*?(?:\s-d\s|\s--detach\b)", cmd, re.I))
            expectations.append(ResourceExpectation("container", name, detached, "container_running" if detached else "container_created_or_exited"))
        for name in re.findall(r"docker\s+(?:container\s+)?(?:rm|stop)\s+(?:-[\w-]+\s+)*([\w.-]+)", cmd, re.I):
            expectations.append(ResourceExpectation("container", name, False, "container_removed"))
        for name in re.findall(r"docker\s+volume\s+create(?:\s+--[\w-]+(?:[= ]\S+)?)?\s+([\w.-]+)", cmd, re.I):
            expectations.append(ResourceExpectation("volume", name, True, "volume_exists"))
        for name in re.findall(r"docker\s+volume\s+rm\s+([\w.-]+)", cmd, re.I):
            expectations.append(ResourceExpectation("volume", name, False, "volume_removed"))
        if re.search(r"docker(?:-compose|\s+compose)[\s\S]*\bup\b", cmd, re.I):
            expectations.append(ResourceExpectation("compose", "services", True, "compose_services_running"))
        if re.search(r"docker(?:-compose|\s+compose)[\s\S]*\bdown\b", cmd, re.I):
            expectations.append(ResourceExpectation("compose", "services", False, "compose_services_removed"))
        for port in self._published_ports(cmd):
            expectations.append(ResourceExpectation("port", port, True, "port_reachable"))
        return expectations

    def evaluate(self, test: TestCase, executions: list[CommandExecution], platform: PlatformInfo, cwd: str | None = None) -> list[AssertionResult]:
        results: list[AssertionResult] = []
        for execution in executions:
            if execution.timed_out:
                results.append(AssertionResult("command_timeout", False, f"Timed out: {execution.command}", TestStatus.TIMEOUT))
            elif execution.exit_code != 0:
                results.append(AssertionResult("command_exit_code", False, f"Exit code {execution.exit_code}: {execution.command}\n{execution.stderr}", TestStatus.FAIL))
            else:
                results.append(AssertionResult("command_exit_code", True, f"Command exited 0: {execution.command}"))
        if any(not r.passed for r in results):
            return results
        expectations = self.infer_expectations(test)
        if not expectations and self._needs_manual(test.command_block):
            results.append(AssertionResult("manual_verification", False, "This packet capture/exfiltration/observability exercise needs human interpretation.", TestStatus.MANUAL_VERIFICATION))
            return results
        for expectation in expectations:
            results.append(self._evaluate_expectation(expectation, cwd))
        if not expectations:
            combined = "\n".join(e.stdout for e in executions)
            results.append(AssertionResult("observable_output", True, "No Docker resource assertion inferred; command completed and output was captured.", details={"stdout_present": bool(combined.strip())}))
        return results

    def _evaluate_expectation(self, expectation: ResourceExpectation, cwd: str | None) -> AssertionResult:
        if expectation.kind == "network":
            exists = self._docker_inspect("network", expectation.name)
        elif expectation.kind == "container":
            if expectation.assertion == "container_running":
                exists = self._docker_container_running(expectation.name)
            else:
                exists = self._docker_inspect("container", expectation.name)
        elif expectation.kind == "volume":
            exists = self._docker_inspect("volume", expectation.name)
        elif expectation.kind == "port":
            exists = self._port_reachable(int(expectation.name))
        elif expectation.kind == "compose":
            exists = self._compose_has_services(cwd)
        else:
            return AssertionResult(expectation.assertion, False, f"Unknown expectation {expectation}", TestStatus.ERROR)
        passed = exists is expectation.should_exist
        status = TestStatus.PASS if passed else TestStatus.FAIL
        verb = "exists/runs" if expectation.should_exist else "is absent"
        return AssertionResult(expectation.assertion, passed, f"{expectation.kind} {expectation.name} expected {verb}; observed exists={exists}", status)

    def _docker_inspect(self, kind: str, name: str) -> bool:
        result = subprocess.run(["docker", kind, "inspect", name], text=True, capture_output=True, check=False, timeout=10)
        return result.returncode == 0

    def _docker_container_running(self, name: str) -> bool:
        result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name], text=True, capture_output=True, check=False, timeout=10)
        return result.returncode == 0 and result.stdout.strip().lower() == "true"

    def _compose_has_services(self, cwd: str | None) -> bool:
        result = subprocess.run(["docker", "compose", "ps", "--status", "running", "--format", "json"], cwd=cwd, text=True, capture_output=True, check=False, timeout=15)
        if result.returncode != 0:
            return False
        return bool(result.stdout.strip())

    def _port_reachable(self, port: int) -> bool:
        deadline = time.time() + 10
        while time.time() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    return True
            time.sleep(0.25)
        return False

    def _published_ports(self, cmd: str) -> Iterable[str]:
        for match in re.findall(r"(?:-p|--publish)\s+([0-9.]*:?\d+):\d+", cmd):
            port = match.split(":")[-1]
            if port.isdigit():
                yield port

    def _needs_manual(self, cmd: str) -> bool:
        return bool(re.search(r"tcpdump|tshark|wireshark|dns exfil|exfiltration|tetragon|bpftool|bpftrace", cmd, re.I))
