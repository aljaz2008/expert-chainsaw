from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any
import time


class TestStatus(str, Enum):
    __test__ = False
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    SKIPPED_UNSUPPORTED = "SKIPPED_UNSUPPORTED"
    MANUAL_VERIFICATION = "MANUAL_VERIFICATION"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


class RiskLevel(str, Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    DANGEROUS = "DANGEROUS"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class PlatformRequirement:
    feature: str
    reason: str
    required: bool = True


@dataclass
class TestCase:
    __test__ = False
    id: str
    chapter: str
    section: str
    subsection: str
    command_block: str
    expected_behavior: str
    cleanup_requirements: list[str] = field(default_factory=list)
    platform_requirements: list[PlatformRequirement] = field(default_factory=list)
    source_file: str = ""
    line_start: int = 0
    kind: str = "bash"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def full_section(self) -> str:
        parts = [self.chapter, self.section, self.subsection]
        return " > ".join(p for p in parts if p)


@dataclass
class AssertionResult:
    name: str
    passed: bool
    message: str
    status: TestStatus = TestStatus.PASS
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandExecution:
    command: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    risk: RiskLevel = RiskLevel.SAFE
    blocked_reason: str = ""


@dataclass
class CleanupResult:
    command: str
    exit_code: int | None
    verified: bool
    message: str
    duration_seconds: float = 0.0


@dataclass
class RootCause:
    category: str
    explanation: str
    suggested_fix: str


@dataclass
class TestResult:
    __test__ = False
    test_case: TestCase
    status: TestStatus
    assertions: list[AssertionResult]
    executions: list[CommandExecution]
    message: str
    started_at: float = field(default_factory=time.time)
    ended_at: float = field(default_factory=time.time)
    warnings: list[str] = field(default_factory=list)
    cleanup_results: list[CleanupResult] = field(default_factory=list)
    root_causes: list[RootCause] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.ended_at - self.started_at)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        for assertion in data["assertions"]:
            assertion["status"] = assertion["status"].value
        for execution in data["executions"]:
            execution["risk"] = execution["risk"].value if hasattr(execution["risk"], "value") else execution["risk"]
        for req in data["test_case"]["platform_requirements"]:
            req.setdefault("required", True)
        return data


def safe_id(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned or "untitled"


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
