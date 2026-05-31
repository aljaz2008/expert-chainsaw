from docker_lab_validator.models import TestCase, PlatformRequirement, TestStatus
from docker_lab_validator.platform import PlatformInfo
from docker_lab_validator.runner import ValidationRunner


def test_runner_attempts_linux_networking_commands_instead_of_pre_skipping(tmp_path):
    platform = PlatformInfo("linux", True, False, False, False, True, True, {"iptables": False})
    runner = ValidationRunner(tmp_path, platform=platform)
    case = TestCase("t1", "C", "S", "", "iptables -S", "chain", [""], [PlatformRequirement("iptables", "actively validate")])
    result = runner.run_test(case)
    assert result.status in {TestStatus.PASS, TestStatus.FAIL}
    assert result.executions


def test_runner_skips_truly_impossible_ebpf_prerequisite(tmp_path):
    platform = PlatformInfo("linux", True, False, False, False, True, True, {"ebpf": False}, feature_details={"ebpf": "missing BTF"})
    runner = ValidationRunner(tmp_path, platform=platform)
    case = TestCase("t2", "C", "S", "", "bpftool prog list", "programs", [""], [PlatformRequirement("ebpf", "requires BTF")])
    result = runner.run_test(case)
    assert result.status == TestStatus.SKIPPED_UNSUPPORTED
    assert "missing BTF" in result.message


def test_runner_executes_simple_non_docker_block(tmp_path):
    platform = PlatformInfo("linux", True, False, False, False, True, True, {})
    runner = ValidationRunner(tmp_path, platform=platform)
    case = TestCase("t1", "C", "S", "", "echo hello", "prints hello")
    result = runner.run_test(case)
    assert result.status == TestStatus.PASS
    assert result.executions[0].stdout.strip() == "hello"
