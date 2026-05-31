from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path
from .models import TestResult, TestStatus, ensure_dir


class ReportGenerator:
    def __init__(self, output_dir: str | Path):
        self.output_dir = ensure_dir(output_dir)

    def statistics(self, results: list[TestResult]) -> dict:
        counts = {status.value.lower(): 0 for status in TestStatus}
        per_chapter: dict[str, dict] = defaultdict(lambda: {"total": 0, "passed": 0, "success_rate": 0.0})
        total_time = 0.0
        for result in results:
            counts[result.status.value.lower()] += 1
            total_time += result.duration_seconds
            chapter = result.test_case.chapter
            per_chapter[chapter]["total"] += 1
            if result.status == TestStatus.PASS:
                per_chapter[chapter]["passed"] += 1
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
            "execution_time_seconds": round(total_time, 3),
            "per_chapter": dict(per_chapter),
        }

    def write_all(self, results: list[TestResult]) -> dict[str, Path]:
        stats = self.statistics(results)
        paths = {
            "json": self.output_dir / "report.json",
            "markdown": self.output_dir / "report.md",
            "html": self.output_dir / "report.html",
        }
        paths["json"].write_text(json.dumps({"statistics": stats, "results": [r.to_dict() for r in results]}, indent=2), encoding="utf-8")
        paths["markdown"].write_text(self._markdown(results, stats), encoding="utf-8")
        paths["html"].write_text(self._html(results, stats), encoding="utf-8")
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
