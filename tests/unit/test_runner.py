from docker_lab_validator.models import TestCase, PlatformRequirement, TestStatus
from docker_lab_validator.platform import PlatformInfo
from docker_lab_validator.runner import ValidationRunner


def test_runner_marks_unsupported_feature_as_skipped(tmp_path):
    platform = PlatformInfo("darwin", False, True, True, False, {"docker": True, "iptables": False})
    runner = ValidationRunner(tmp_path, platform=platform)
    case = TestCase("t1", "C", "S", "", "iptables -S", "chain", [""], [PlatformRequirement("iptables", "Linux only")])
    result = runner.run_test(case)
    assert result.status == TestStatus.SKIPPED_UNSUPPORTED
    assert "iptables" in result.message


def test_runner_executes_simple_non_docker_block(tmp_path):
    platform = PlatformInfo("linux", True, False, False, False, {})
    runner = ValidationRunner(tmp_path, platform=platform)
    case = TestCase("t1", "C", "S", "", "echo hello", "prints hello")
    result = runner.run_test(case)
    assert result.status == TestStatus.PASS
    assert result.executions[0].stdout.strip() == "hello"
