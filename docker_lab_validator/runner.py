from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Iterable
from .assertions import DockerAssertionEngine
from .checkpoint import CheckpointStore
from .cleanup import CleanupManager
from .diagnostics import RootCauseAnalyzer
from .logging_utils import configure_loggers
from .models import AssertionResult, CommandExecution, CleanupResult, TestCase, TestResult, TestStatus, RiskLevel, ensure_dir
from .parser import MarkdownLabParser
from .platform import PlatformDetector, PlatformInfo
from .reports import ReportGenerator
from .safety import CommandSafetyClassifier, split_shell_commands


class ValidationRunner:
    def __init__(self, output_dir: str | Path = "reports", timeout: int = 120, cleanup: bool = True, platform: PlatformInfo | None = None):
        self.output_dir = ensure_dir(output_dir)
        self.timeout = timeout
        self.cleanup_enabled = cleanup
        self.platform = platform or PlatformDetector().detect()
        self.loggers = configure_loggers(self.output_dir)
        self.assertions = DockerAssertionEngine()
        self.cleanup = CleanupManager(self.loggers["cleanup"])
        self.checkpoint = CheckpointStore(self.output_dir)
        self.safety = CommandSafetyClassifier()
        self.diagnostics = RootCauseAnalyzer()

    def load_tests(self, markdown_files: Iterable[str | Path]) -> list[TestCase]:
        parser = MarkdownLabParser()
        tests: list[TestCase] = []
        seen: set[str] = set()
        for path in markdown_files:
            for test in parser.parse_file(path):
                original = test.id
                n = 2
                while test.id in seen:
                    test.id = f"{original}-{n}"
                    n += 1
                seen.add(test.id)
                tests.append(test)
        return tests

    def run_documents(self, markdown_files: Iterable[str | Path], resume: bool = False, chapter: str | None = None, section: str | None = None, test_id: str | None = None) -> list[TestResult]:
        tests = self.filter_tests(self.load_tests(markdown_files), chapter=chapter, section=section, test_id=test_id)
        results = self.run_tests(tests, resume=resume)
        ReportGenerator(self.output_dir, self.platform).write_all(results)
        return results

    def filter_tests(self, tests: list[TestCase], chapter: str | None = None, section: str | None = None, test_id: str | None = None) -> list[TestCase]:
        selected = tests
        if chapter:
            selected = [t for t in selected if chapter.lower() in t.chapter.lower()]
        if section:
            selected = [t for t in selected if section.lower() in t.section.lower() or section.lower() in t.subsection.lower()]
        if test_id:
            selected = [t for t in selected if t.id == test_id]
        return selected

    def run_tests(self, tests: list[TestCase], resume: bool = False) -> list[TestResult]:
        results: list[TestResult] = []
        current_chapter: str | None = None
        for test in tests:
            if current_chapter is not None and test.chapter != current_chapter and self.cleanup_enabled:
                self._cleanup_after_chapter(current_chapter)
            current_chapter = test.chapter
            if resume and self.checkpoint.has_result(test.id):
                continue
            result = self.run_test(test)
            self.checkpoint.save_result(result)
            results.append(result)
        if current_chapter is not None and self.cleanup_enabled:
            self._cleanup_after_chapter(current_chapter)
        return results

    def run_test(self, test: TestCase) -> TestResult:
        started = time.time()
        unsupported = self._unsupported_requirements(test)
        desktop_warnings = self._desktop_warnings(test)
        if unsupported:
            message = "; ".join(f"{r.feature}: {self.platform.reason(r.feature)} {r.reason}" for r in unsupported)
            assertions = [AssertionResult("platform_support", False, message, TestStatus.SKIPPED_UNSUPPORTED)]
            result = TestResult(test, TestStatus.SKIPPED_UNSUPPORTED, assertions, [], message, started_at=started, ended_at=time.time(), warnings=desktop_warnings)
            self._log_result(result)
            return result
        with tempfile.TemporaryDirectory(prefix="docker-lab-validator-") as tmp:
            executions = self._execute_block(test.command_block, tmp)
            cleanup_results: list[CleanupResult] = []
            try:
                assertion_results = self.assertions.evaluate(test, executions, self.platform, cwd=tmp)
                status = self._status_from_assertions(assertion_results, desktop_warnings)
                message = self._message(assertion_results, desktop_warnings)
            except Exception as exc:
                self.loggers["errors"].exception("assertion error for %s", test.id)
                assertion_results = [AssertionResult("framework_error", False, str(exc), TestStatus.ERROR)]
                status = TestStatus.ERROR
                message = str(exc)
            finally:
                if self.cleanup_enabled:
                    try:
                        cleanup_results = self.cleanup.cleanup_for_test(test, cwd=tmp)
                    except Exception:
                        self.loggers["errors"].exception("cleanup error for %s", test.id)
            root_causes = self.diagnostics.analyze(executions, [message]) if status in {TestStatus.FAIL, TestStatus.ERROR, TestStatus.TIMEOUT} else []
            result = TestResult(test, status, assertion_results, executions, message, started_at=started, ended_at=time.time(), warnings=desktop_warnings, cleanup_results=cleanup_results, root_causes=root_causes)
            self._log_result(result)
            return result

    def _unsupported_requirements(self, test: TestCase):
        unsupported = []
        for req in test.platform_requirements:
            if not req.required:
                continue
            if self.platform.supports(req.feature):
                continue
            # On the Ubuntu VM most Linux/networking commands should be attempted; only
            # truly impossible prerequisites are skipped before execution.
            if req.feature in {"docker", "compose", "ebpf", "tetragon"}:
                unsupported.append(req)
        return unsupported

    def _execute_block(self, command_block: str, cwd: str) -> list[CommandExecution]:
        executions: list[CommandExecution] = []
        for command in split_shell_commands(command_block):
            assessment = self.safety.assess(command)
            if assessment.risk in {RiskLevel.BLOCKED, RiskLevel.DANGEROUS}:
                self.loggers["execution"].error("blocked risk=%s reason=%s command=%s", assessment.risk.value, assessment.reason, command)
                executions.append(CommandExecution(command, None, "", "", 0.0, False, assessment.risk, assessment.reason))
                continue
            if assessment.risk == RiskLevel.CAUTION:
                self.loggers["execution"].warning("CAUTION command executing: %s (%s)", command, assessment.reason)
            self.loggers["execution"].info("start risk=%s command=%s", assessment.risk.value, command)
            started = time.time()
            try:
                env = os.environ.copy()
                env.setdefault("DEBIAN_FRONTEND", "noninteractive")
                env.setdefault("APT_LISTCHANGES_FRONTEND", "none")
                proc = subprocess.run(["bash", "-lc", command], cwd=cwd, text=True, capture_output=True, timeout=self.timeout, check=False, env=env)
                execution = CommandExecution(command, proc.returncode, proc.stdout, proc.stderr, time.time() - started, False, assessment.risk)
            except subprocess.TimeoutExpired as exc:
                execution = CommandExecution(command, None, exc.stdout or "", exc.stderr or "", time.time() - started, True, assessment.risk)
            self.loggers["execution"].info("finish exit=%s timeout=%s duration=%.3f command=%s", execution.exit_code, execution.timed_out, execution.duration_seconds, command)
            executions.append(execution)
        return executions

    def _status_from_assertions(self, assertions: list[AssertionResult], warnings: list[str]) -> TestStatus:
        priority = [TestStatus.ERROR, TestStatus.TIMEOUT, TestStatus.FAIL, TestStatus.MANUAL_VERIFICATION, TestStatus.SKIPPED_UNSUPPORTED]
        for status in priority:
            if any(a.status == status and not a.passed for a in assertions):
                return status
        if warnings:
            return TestStatus.WARNING
        return TestStatus.PASS

    def _message(self, assertions: list[AssertionResult], warnings: list[str]) -> str:
        failed = [a.message for a in assertions if not a.passed]
        base = "; ".join(failed) if failed else "All inferred semantic assertions passed."
        if warnings:
            base += " Warnings: " + "; ".join(warnings)
        return base

    def _desktop_warnings(self, test: TestCase) -> list[str]:
        if not self.platform.is_docker_desktop:
            return []
        impacted = {"host_network", "docker0", "iptables", "nftables", "ip_netns", "tcpdump", "macvlan", "ipvlan"}
        present = {r.feature for r in test.platform_requirements}
        if impacted & present:
            return ["Docker Desktop networking is VM-backed; observed behavior may differ from native Linux."]
        return []

    def _cleanup_after_chapter(self, chapter: str) -> None:
        self.loggers["cleanup"].info("chapter cleanup start: %s", chapter)
        self.cleanup.cleanup_all_known()
        self.loggers["cleanup"].info("chapter cleanup complete: %s", chapter)

    def _log_result(self, result: TestResult) -> None:
        for assertion in result.assertions:
            self.loggers["assertions"].info("%s %s %s %s", result.test_case.id, assertion.name, assertion.status.value, assertion.message)
        for cleanup in result.cleanup_results:
            self.loggers["cleanup"].info("%s cleanup verified=%s exit=%s %s", result.test_case.id, cleanup.verified, cleanup.exit_code, cleanup.command)
        if result.status in {TestStatus.ERROR, TestStatus.FAIL, TestStatus.TIMEOUT}:
            self.loggers["errors"].error("%s %s %s", result.test_case.id, result.status.value, result.message)
            for cause in result.root_causes:
                self.loggers["errors"].error("%s RCA %s %s fix=%s", result.test_case.id, cause.category, cause.explanation, cause.suggested_fix)
