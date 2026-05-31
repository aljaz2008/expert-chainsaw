from __future__ import annotations

import re
from .models import CommandExecution, RootCause


class RootCauseAnalyzer:
    def analyze(self, executions: list[CommandExecution], messages: list[str]) -> list[RootCause]:
        findings: list[RootCause] = []
        text = "\n".join([*(e.stderr + "\n" + e.stdout for e in executions), *messages]).lower()
        rules = [
            ("missing_package", r"command not found|no such file or directory", "Install the missing tool with apt-get install, or correct the command name."),
            ("missing_privilege", r"permission denied|operation not permitted|must be root|are you root", "Run the validator with root privileges or sudo in the disposable VM."),
            ("docker_not_running", r"cannot connect to the docker daemon|is the docker daemon running", "Start Docker with systemctl start docker and verify docker info works."),
            ("kernel_limitation", r"not supported|operation not supported|btf|bpf|kernel", "Verify the Ubuntu kernel supports the requested networking/eBPF capability."),
            ("port_conflict", r"port is already allocated|address already in use", "Free the conflicting port or update the lab guide to use an unused port."),
            ("network_conflict", r"already exists|pool overlaps|overlap", "Clean stale Docker networks/namespaces or use unique lab resource names."),
            ("incorrect_command", r"unknown flag|invalid reference|invalid option|syntax error", "Correct the command syntax in the training document."),
        ]
        seen: set[str] = set()
        for category, pattern, fix in rules:
            if re.search(pattern, text) and category not in seen:
                seen.add(category)
                findings.append(RootCause(category, f"Detected {category.replace('_', ' ')} indicators in command output or assertions.", fix))
        if not findings and any(e.exit_code not in (0, None) for e in executions):
            findings.append(RootCause("unknown_failure", "A command failed but no known failure signature matched.", "Inspect execution.log, stderr, and the generated failure report for command-specific details."))
        return findings
