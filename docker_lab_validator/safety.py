from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from .models import RiskLevel


@dataclass(frozen=True)
class RiskAssessment:
    risk: RiskLevel
    reason: str = ""


class CommandSafetyClassifier:
    """Classify commands for an Ubuntu disposable-lab VM.

    SAFE and CAUTION execute automatically. BLOCKED never executes. DANGEROUS is
    currently treated as BLOCKED unless a future policy explicitly enables it.
    """

    BLOCKED_PATTERNS = [
        (re.compile(r"\brm\s+-r[f]?\s+(?:--no-preserve-root\s+)?/(?:\s|$)|\brm\s+-r[f]?\s+/\*"), "filesystem root deletion"),
        (re.compile(r"\brm\s+-r[f]?\s+(?!/tmp/)[/~][^;&|]*"), "arbitrary directory deletion"),
        (re.compile(r"\b(shutdown|reboot|halt|poweroff)\b"), "power-control command"),
        (re.compile(r"\b(mkfs|fdisk|parted)\b"), "disk/filesystem destruction tool"),
        (re.compile(r"\b(userdel|groupdel)\b"), "user/group deletion"),
        (re.compile(r"passwd\s+root|chpasswd"), "root password modification"),
        (re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*}\s*;\s*:"), "fork bomb"),
        (re.compile(r"\b(curl|wget)\b[^\n|;]*(\||>)\s*(sudo\s+)?(sh|bash)\b", re.I), "remote script execution"),
        (re.compile(r"\b(sh|bash)\s+-c\s+['\"]?\$\(\s*(curl|wget)\b", re.I), "remote script execution"),
    ]
    CAUTION_PATTERNS = [
        re.compile(r"\bapt(?:-get)?\s+install\b"),
        re.compile(r"\bdocker\s+swarm\s+init\b|\bdocker\s+service\s+create\b"),
        re.compile(r"\biptables\b.*\s-[AIRDF]\b|\bnft\b\s+(add|delete|flush|insert|create)\b"),
        re.compile(r"\bip\s+netns\s+(add|delete|exec)\b"),
        re.compile(r"\btcpdump\b"),
        re.compile(r"\bsystemctl\b"),
    ]

    def assess(self, command: str) -> RiskAssessment:
        normalized = " ".join(command.strip().split())
        for pattern, reason in self.BLOCKED_PATTERNS:
            if pattern.search(normalized):
                return RiskAssessment(RiskLevel.BLOCKED, reason)
        for pattern in self.CAUTION_PATTERNS:
            if pattern.search(normalized):
                return RiskAssessment(RiskLevel.CAUTION, "stateful Linux lab operation; allowed on disposable Ubuntu VM")
        return RiskAssessment(RiskLevel.SAFE, "safe lab command")


def split_shell_commands(command_block: str) -> list[str]:
    """Split common lab code blocks into executable commands.

    The splitter intentionally handles the normal shape of training docs:
    one command per line with optional backslash continuations. Complex shell
    control flow is preserved as one bash snippet so it still executes.
    """
    logical: list[str] = []
    current = ""
    for raw in command_block.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            current += line[:-1] + " "
            continue
        current += line
        logical.append(current.strip())
        current = ""
    if current.strip():
        logical.append(current.strip())
    if not logical:
        return []
    control = re.compile(r"\b(if|for|while|case|function)\b|\bthen\b|\bfi\b|\bdone\b|[{}]")
    if len(logical) > 1 and any(control.search(cmd) for cmd in logical):
        return [command_block]
    return logical
