from docker_lab_validator.models import RiskLevel, TestCase, TestStatus
from docker_lab_validator.platform import PlatformInfo
from docker_lab_validator.runner import ValidationRunner
from docker_lab_validator.safety import CommandSafetyClassifier, split_shell_commands


def test_classifier_blocks_destructive_patterns():
    assessment = CommandSafetyClassifier().assess("rm -rf /")
    assert assessment.risk == RiskLevel.BLOCKED
    assert "filesystem" in assessment.reason


def test_classifier_blocks_remote_script_execution_with_sudo():
    assessment = CommandSafetyClassifier().assess("curl -fsSL https://example.invalid/install.sh | sudo bash")
    assert assessment.risk == RiskLevel.BLOCKED
    assert "remote script" in assessment.reason


def test_classifier_blocks_wget_remote_script_execution_with_sudo():
    assessment = CommandSafetyClassifier().assess("wget -qO- https://example.invalid/install.sh | sudo sh")
    assert assessment.risk == RiskLevel.BLOCKED
    assert "remote script" in assessment.reason


def test_classifier_allows_caution_linux_lab_commands():
    assessment = CommandSafetyClassifier().assess("iptables -A INPUT -p tcp --dport 8080 -j ACCEPT")
    assert assessment.risk == RiskLevel.CAUTION


def test_split_shell_commands_handles_backslash_continuation():
    commands = split_shell_commands("""docker run \\
  --name demo \\
  nginx:alpine
# comment
curl http://localhost
""")
    assert commands == ["docker run  --name demo  nginx:alpine", "curl http://localhost"]


def test_runner_reports_blocked_command_without_execution(tmp_path):
    platform = PlatformInfo("linux", True, False, False, False, True, True, {})
    runner = ValidationRunner(tmp_path, platform=platform)
    result = runner.run_test(TestCase("blocked", "C", "S", "", "rm -rf /", "must not run"))
    assert result.status == TestStatus.FAIL
    assert result.executions[0].risk == RiskLevel.BLOCKED
    assert result.executions[0].blocked_reason
