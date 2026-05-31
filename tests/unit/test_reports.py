from docker_lab_validator.models import AssertionResult, TestCase, TestResult, TestStatus
from docker_lab_validator.reports import ReportGenerator


def test_report_generator_writes_all_formats(tmp_path):
    case = TestCase("id1", "Chapter", "Section", "", "echo ok", "ok")
    result = TestResult(case, TestStatus.PASS, [AssertionResult("a", True, "ok")], [], "ok")
    paths = ReportGenerator(tmp_path).write_all([result])
    assert paths["json"].exists()
    assert paths["markdown"].read_text().startswith("# Docker Lab Validation Report")
    assert "PASS" in paths["html"].read_text()
    stats = ReportGenerator(tmp_path).statistics([result])
    assert stats["total_tests"] == 1
    assert stats["passed"] == 1
    assert stats["per_chapter"]["Chapter"]["success_rate"] == 100.0
