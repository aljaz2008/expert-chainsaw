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
    details: dict[str, str] | None = None


class DockerAssertionEngine:
    """Infer and evaluate semantic state assertions for Ubuntu lab commands."""

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
            expectations.append(ResourceExpectation("compose", "services", True, "compose_services_running_or_healthy"))
        if re.search(r"docker(?:-compose|\s+compose)[\s\S]*\bdown\b", cmd, re.I):
            expectations.append(ResourceExpectation("compose", "services", False, "compose_services_removed"))
        for port in self._published_ports(cmd):
            expectations.append(ResourceExpectation("port", port, True, "port_reachable"))
        for name in re.findall(r"\bip\s+netns\s+add\s+([\w.-]+)", cmd, re.I):
            expectations.append(ResourceExpectation("netns", name, True, "namespace_exists"))
        for name in re.findall(r"\bip\s+netns\s+(?:del|delete)\s+([\w.-]+)", cmd, re.I):
            expectations.append(ResourceExpectation("netns", name, False, "namespace_removed"))
        for rule in self._iptables_added_rules(cmd):
            expectations.append(ResourceExpectation("iptables", rule, True, "iptables_rule_exists"))
        for rule in self._iptables_deleted_rules(cmd):
            expectations.append(ResourceExpectation("iptables", rule, False, "iptables_rule_removed"))
        if re.search(r"\bdocker\s+swarm\s+init\b", cmd, re.I):
            expectations.append(ResourceExpectation("swarm", "local", True, "swarm_active"))
        for name in re.findall(r"docker\s+service\s+create[\s\S]*?(?:--name\s+|--name=)([\w.-]+)", cmd, re.I):
            expectations.append(ResourceExpectation("service", name, True, "service_exists"))
        for name in re.findall(r"docker\s+service\s+rm\s+([\w.-]+)", cmd, re.I):
            expectations.append(ResourceExpectation("service", name, False, "service_removed"))
        if re.search(r"\bnft\s+(?:add|insert|create)\b", cmd, re.I):
            expectations.append(ResourceExpectation("nft", "ruleset", True, "nft_ruleset_readable"))
        if re.search(r"\btcpdump\b", cmd, re.I):
            expectations.append(ResourceExpectation("packet_capture", "tcpdump", True, "packet_capture_executed"))
        expectations.extend(self._observation_expectations(test.expected_behavior))
        return self._dedupe(expectations)

    def evaluate(self, test: TestCase, executions: list[CommandExecution], platform: PlatformInfo, cwd: str | None = None) -> list[AssertionResult]:
        results: list[AssertionResult] = []
        for execution in executions:
            if execution.blocked_reason:
                results.append(AssertionResult("command_blocked", False, f"Blocked {execution.command}: {execution.blocked_reason}", TestStatus.FAIL))
            elif execution.timed_out:
                results.append(AssertionResult("command_timeout", False, f"Timed out: {execution.command}", TestStatus.TIMEOUT))
            elif execution.exit_code != 0:
                results.append(AssertionResult("command_exit_code", False, f"Exit code {execution.exit_code}: {execution.command}\n{execution.stderr}", TestStatus.FAIL))
            else:
                results.append(AssertionResult("command_exit_code", True, f"Command exited 0: {execution.command}", details={"risk": execution.risk.value}))
        if any(not r.passed for r in results):
            return results
        expectations = self.infer_expectations(test)
        if not expectations and self._needs_manual(test.command_block):
            results.append(AssertionResult("manual_verification", False, "Exercise executed but packet/exfiltration/observability meaning needs human interpretation.", TestStatus.MANUAL_VERIFICATION))
            return results
        for expectation in expectations:
            results.append(self._evaluate_expectation(expectation, cwd, executions))
        if not expectations:
            combined = "\n".join(e.stdout for e in executions)
            results.append(AssertionResult("observable_output", True, "No resource assertion inferred; command completed and output was captured.", details={"stdout_present": bool(combined.strip())}))
        return results

    def _evaluate_expectation(self, expectation: ResourceExpectation, cwd: str | None, executions: list[CommandExecution]) -> AssertionResult:
        if expectation.kind == "network":
            exists = self._docker_inspect("network", expectation.name)
        elif expectation.kind == "container":
            exists = self._docker_container_running(expectation.name) if expectation.assertion == "container_running" else self._docker_inspect("container", expectation.name)
        elif expectation.kind == "volume":
            exists = self._docker_inspect("volume", expectation.name)
        elif expectation.kind == "port":
            exists = self._port_reachable(int(expectation.name))
        elif expectation.kind == "compose":
            exists = self._compose_has_services(cwd)
        elif expectation.kind == "netns":
            exists = self._netns_exists(expectation.name)
        elif expectation.kind == "iptables":
            exists = self._iptables_rule_exists(expectation.name)
        elif expectation.kind == "swarm":
            exists = self._swarm_active()
        elif expectation.kind == "service":
            exists = self._service_exists(expectation.name)
        elif expectation.kind == "nft":
            exists = self._command_ok(["nft", "list", "ruleset"])
        elif expectation.kind == "packet_capture":
            exists = any("tcpdump" in e.command and e.exit_code == 0 for e in executions)
        elif expectation.kind == "http_response":
            exists = self._http_observed_or_reachable(expectation.name, executions)
        else:
            return AssertionResult(expectation.assertion, False, f"Unknown expectation {expectation}", TestStatus.ERROR)
        passed = exists is expectation.should_exist
        status = TestStatus.PASS if passed else TestStatus.FAIL
        verb = "exists/runs" if expectation.should_exist else "is absent"
        return AssertionResult(expectation.assertion, passed, f"{expectation.kind} {expectation.name} expected {verb}; observed exists={exists}", status)

    def _docker_inspect(self, kind: str, name: str) -> bool:
        return self._command_ok(["docker", kind, "inspect", name])

    def _docker_container_running(self, name: str) -> bool:
        result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name], text=True, capture_output=True, check=False, timeout=10)
        return result.returncode == 0 and result.stdout.strip().lower() == "true"

    def _compose_has_services(self, cwd: str | None) -> bool:
        result = subprocess.run(["docker", "compose", "ps", "--format", "json"], cwd=cwd, text=True, capture_output=True, check=False, timeout=20)
        if result.returncode != 0:
            return False
        output = result.stdout.strip().lower()
        return bool(output) and "exited" not in output and "dead" not in output

    def _port_reachable(self, port: int) -> bool:
        deadline = time.time() + 10
        while time.time() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    return True
            time.sleep(0.25)
        return False

    def _netns_exists(self, name: str) -> bool:
        result = subprocess.run(["ip", "netns", "list"], text=True, capture_output=True, check=False, timeout=10)
        return result.returncode == 0 and any(line.split()[0] == name for line in result.stdout.splitlines() if line.strip())

    def _iptables_rule_exists(self, check_rule: str) -> bool:
        args = check_rule.split()
        if not args:
            return False
        result = subprocess.run(["iptables", *args], text=True, capture_output=True, check=False, timeout=10)
        return result.returncode == 0

    def _swarm_active(self) -> bool:
        result = subprocess.run(["docker", "info", "--format", "{{.Swarm.LocalNodeState}}"], text=True, capture_output=True, check=False, timeout=10)
        return result.returncode == 0 and result.stdout.strip().lower() == "active"

    def _service_exists(self, name: str) -> bool:
        return self._command_ok(["docker", "service", "inspect", name])

    def _command_ok(self, args: list[str]) -> bool:
        try:
            result = subprocess.run(args, text=True, capture_output=True, check=False, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    def _published_ports(self, cmd: str) -> Iterable[str]:
        for match in re.findall(r"(?:-p|--publish)\s+([0-9.]*:?\d+):\d+", cmd):
            port = match.split(":")[-1]
            if port.isdigit():
                yield port

    def _iptables_added_rules(self, cmd: str) -> Iterable[str]:
        for line in cmd.splitlines():
            stripped = line.strip()
            match = re.match(r"iptables\s+(-[AI])\s+(.*)", stripped)
            if match:
                yield "-C " + match.group(2)

    def _iptables_deleted_rules(self, cmd: str) -> Iterable[str]:
        for line in cmd.splitlines():
            stripped = line.strip()
            match = re.match(r"iptables\s+-D\s+(.*)", stripped)
            if match:
                yield "-C " + match.group(1)

    def _observation_expectations(self, expected_behavior: str) -> list[ResourceExpectation]:
        text = expected_behavior.lower()
        expectations: list[ResourceExpectation] = []
        for url in re.findall(r"https?://[^\s`'\"]+", expected_behavior):
            expectations.append(ResourceExpectation("http_response", url, True, "http_response_expected"))
        if "http" in text and not expectations:
            expectations.append(ResourceExpectation("http_response", "observed-output", True, "http_response_expected"))
        return expectations

    def _http_observed_or_reachable(self, target: str, executions: list[CommandExecution]) -> bool:
        combined = "\n".join(e.stdout + "\n" + e.stderr for e in executions).lower()
        if re.search(r"http/[0-9.]+\s+2\d\d|\b2\d\d\b|ok|welcome", combined):
            return True
        if target.startswith("http"):
            result = subprocess.run(["curl", "-fsS", "--max-time", "5", target], text=True, capture_output=True, check=False, timeout=8)
            return result.returncode == 0
        return False

    def _needs_manual(self, cmd: str) -> bool:
        return bool(re.search(r"dns exfil|exfiltration|tetragon|bpftool|bpftrace", cmd, re.I))

    def _dedupe(self, expectations: list[ResourceExpectation]) -> list[ResourceExpectation]:
        seen: set[tuple[str, str, bool, str]] = set()
        unique: list[ResourceExpectation] = []
        for exp in expectations:
            key = (exp.kind, exp.name, exp.should_exist, exp.assertion)
            if key not in seen:
                seen.add(key)
                unique.append(exp)
        return unique
