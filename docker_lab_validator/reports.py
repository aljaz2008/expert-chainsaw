from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path
from .models import TestResult, TestStatus, RiskLevel, ensure_dir
from .platform import PlatformInfo


class ReportGenerator:
    def __init__(self, output_dir: str | Path, platform: PlatformInfo | None = None):
        self.output_dir = ensure_dir(output_dir)
        self.platform = platform

    def statistics(self, results: list[TestResult]) -> dict:
        counts = {status.value.lower(): 0 for status in TestStatus}
        per_chapter: dict[str, dict] = defaultdict(lambda: {"total": 0, "passed": 0, "success_rate": 0.0})
        total_time = 0.0
        commands_parsed = commands_executed = commands_blocked = commands_failed = commands_passed = 0
        assertions_passed = assertions_failed = 0
        cleanup_total = cleanup_verified = 0
        for result in results:
            counts[result.status.value.lower()] += 1
            total_time += result.duration_seconds
            chapter = result.test_case.chapter
            per_chapter[chapter]["total"] += 1
            if result.status == TestStatus.PASS:
                per_chapter[chapter]["passed"] += 1
            commands_parsed += max(1, len(result.executions))
            for execution in result.executions:
                if execution.blocked_reason or execution.risk == RiskLevel.BLOCKED:
                    commands_blocked += 1
                else:
                    commands_executed += 1
                    if execution.exit_code == 0 and not execution.timed_out:
                        commands_passed += 1
                    else:
                        commands_failed += 1
            for assertion in result.assertions:
                if assertion.passed:
                    assertions_passed += 1
                else:
                    assertions_failed += 1
            cleanup_total += len(result.cleanup_results)
            cleanup_verified += sum(1 for cleanup in result.cleanup_results if cleanup.verified)
        for chapter in per_chapter.values():
            chapter["success_rate"] = round((chapter["passed"] / chapter["total"] * 100), 2) if chapter["total"] else 0.0
        return {
            "total_tests": len(results),
            "passed": counts["pass"],
            "failed": counts["fail"],
            "warnings": counts["warning"],
            "skipped": counts["skipped_unsupported"],
            "manual_verification": counts["manual_verification"],
            "timeouts": counts["timeout"],
            "errors": counts["error"],
            "commands_parsed": commands_parsed,
            "commands_executed": commands_executed,
            "commands_blocked": commands_blocked,
            "commands_failed": commands_failed,
            "commands_passed": commands_passed,
            "commands_skipped": counts["skipped_unsupported"],
            "assertions_passed": assertions_passed,
            "assertions_failed": assertions_failed,
            "cleanup_success_rate": round((cleanup_verified / cleanup_total * 100), 2) if cleanup_total else 100.0,
            "execution_time_seconds": round(total_time, 3),
            "per_chapter": dict(per_chapter),
        }

    def write_all(self, results: list[TestResult]) -> dict[str, Path]:
        stats = self.statistics(results)
        paths = {
            "json": self.output_dir / "report.json",
            "markdown": self.output_dir / "report.md",
            "html": self.output_dir / "report.html",
            "compatibility": self.output_dir / "compatibility_report.md",
            "failure": self.output_dir / "failure_report.md",
            "execution": self.output_dir / "execution_report.md",
        }
        payload = {"statistics": stats, "platform": self._platform_dict(), "results": [r.to_dict() for r in results]}
        paths["json"].write_text(json.dumps(payload, indent=2), encoding="utf-8")
        paths["markdown"].write_text(self._markdown(results, stats), encoding="utf-8")
        paths["html"].write_text(self._html(results, stats), encoding="utf-8")
        paths["compatibility"].write_text(self._compatibility(), encoding="utf-8")
        paths["failure"].write_text(self._failure_report(results), encoding="utf-8")
        paths["execution"].write_text(self._execution_report(results, stats), encoding="utf-8")
        return paths

    def _markdown(self, results: list[TestResult], stats: dict) -> str:
        lines = ["# Docker Lab Validation Report", "", "## Statistics", ""]
        for key, value in stats.items():
            if key != "per_chapter":
                lines.append(f"- **{key.replace('_', ' ').title()}**: {value}")
        lines.extend(["", "## Per Chapter", "", "| Chapter | Total | Passed | Success Rate |", "|---|---:|---:|---:|"])
        for chapter, data in stats["per_chapter"].items():
            lines.append(f"| {chapter} | {data['total']} | {data['passed']} | {data['success_rate']}% |")
        lines.extend(["", "## Results", "", "| ID | Status | Section | Message |", "|---|---|---|---|"])
        for result in results:
            msg = result.message.replace("|", "\\|").replace("\n", "<br>")
            lines.append(f"| `{result.test_case.id}` | **{result.status.value}** | {result.test_case.full_section} | {msg} |")
        return "\n".join(lines) + "\n"

    def _html(self, results: list[TestResult], stats: dict) -> str:
        rows = []
        for result in results:
            rows.append("<tr>" + "".join([
                f"<td><code>{html.escape(result.test_case.id)}</code></td>",
                f"<td class='{html.escape(result.status.value.lower())}'>{html.escape(result.status.value)}</td>",
                f"<td>{html.escape(result.test_case.full_section)}</td>",
                f"<td>{html.escape(result.message)}</td>",
            ]) + "</tr>")
        stats_items = "".join(f"<li><strong>{html.escape(str(k))}</strong>: {html.escape(str(v))}</li>" for k, v in stats.items() if k != "per_chapter")
        return f"""<!doctype html>
<html><head><meta charset='utf-8'><title>Docker Lab Validation Report</title>
<style>body{{font-family:system-ui,sans-serif;margin:2rem}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:.5rem}}.pass{{color:#087f23}}.fail,.error,.timeout{{color:#b00020}}.warning,.manual_verification{{color:#9a6700}}.skipped_unsupported{{color:#57606a}}</style></head>
<body><h1>Docker Lab Validation Report</h1><h2>Statistics</h2><ul>{stats_items}</ul><h2>Results</h2><table><thead><tr><th>ID</th><th>Status</th><th>Section</th><th>Message</th></tr></thead><tbody>{''.join(rows)}</tbody></table></body></html>"""

    def _compatibility(self) -> str:
        if not self.platform:
            return "# Compatibility Report\n\nNo platform information was supplied.\n"
        lines = ["# Compatibility Report", "", f"- OS: `{self.platform.os_name}`", f"- Linux: `{self.platform.is_linux}`", f"- Root: `{self.platform.is_root}`", f"- Docker Desktop: `{self.platform.is_docker_desktop}`", f"- Rootless Docker: `{self.platform.is_rootless}`", "", "| Feature | Available | Detail |", "|---|---:|---|"]
        for feature in sorted(self.platform.features):
            lines.append(f"| {feature} | {self.platform.features[feature]} | {self.platform.reason(feature)} |")
        if self.platform.warnings:
            lines.extend(["", "## Warnings", *[f"- {warning}" for warning in self.platform.warnings]])
        return "\n".join(lines) + "\n"

    def _failure_report(self, results: list[TestResult]) -> str:
        lines = ["# Failure Report", ""]
        failures = [r for r in results if r.status in {TestStatus.FAIL, TestStatus.ERROR, TestStatus.TIMEOUT}]
        if not failures:
            lines.append("No failures detected.")
            return "\n".join(lines) + "\n"
        for result in failures:
            lines.extend([f"## {result.test_case.id}", "", f"- Status: `{result.status.value}`", f"- Section: {result.test_case.full_section}", f"- Message: {result.message}", ""])
            for cause in result.root_causes:
                lines.extend([f"### Root Cause: {cause.category}", cause.explanation, f"Suggested fix: {cause.suggested_fix}", ""])
        return "\n".join(lines) + "\n"

    def _execution_report(self, results: list[TestResult], stats: dict) -> str:
        lines = ["# Execution Report", "", "## Command Statistics", ""]
        for key in ["commands_parsed", "commands_executed", "commands_blocked", "commands_passed", "commands_failed", "commands_skipped", "assertions_passed", "assertions_failed", "cleanup_success_rate", "execution_time_seconds"]:
            lines.append(f"- **{key.replace('_', ' ').title()}**: {stats[key]}")
        lines.extend(["", "## Commands", "", "| Test | Risk | Exit | Seconds | Command |", "|---|---|---:|---:|---|"])
        for result in results:
            for execution in result.executions:
                command = execution.command.replace("|", "\\|")
                lines.append(f"| `{result.test_case.id}` | {execution.risk.value} | {execution.exit_code} | {execution.duration_seconds:.3f} | `{command}` |")
        return "\n".join(lines) + "\n"

    def _platform_dict(self) -> dict:
        if not self.platform:
            return {}
        return {
            "os_name": self.platform.os_name,
            "is_linux": self.platform.is_linux,
            "is_root": self.platform.is_root,
            "is_docker_desktop": self.platform.is_docker_desktop,
            "is_rootless": self.platform.is_rootless,
            "features": self.platform.features,
            "warnings": self.platform.warnings,
            "feature_details": self.platform.feature_details,
        }
