# Docker Lab Validator

A production-oriented automated lab validation platform for large hands-on Docker networking and Docker security courses written in Markdown. The primary target is a disposable Ubuntu 24.04 LTS VM with root access, Docker Engine, Docker Compose, apt, and Linux networking privileges.

## What it validates

The framework parses every Bash-compatible fenced code block in Markdown and turns it into a test case with:

- unique id
- chapter, section, and subsection context
- command block
- expected behavior extracted from nearby expected/observation/verification sections or inferred from command semantics
- cleanup requirements
- platform requirements

It actively executes Docker, Docker Compose, bridge/host/none/overlay/macvlan/ipvlan/IPv6/rootless labs, firewall labs, DNS/service-discovery labs, namespace labs, metadata-service exercises, tcpdump/conntrack/iptables/nftables/eBPF/Tetragon exercises, security validation exercises, setup commands, and cleanup exercises whenever the Ubuntu VM can support them.

## Status model

- `PASS`: commands ran and semantic assertions passed
- `FAIL`: command or semantic assertion failed
- `WARNING`: validation passed but Docker Desktop/rootless/native-Linux behavior may differ
- `SKIPPED_UNSUPPORTED`: the platform cannot support a truly impossible prerequisite after capability checks, such as unavailable Docker or missing eBPF/BTF prerequisites
- `MANUAL_VERIFICATION`: exercise requires human interpretation, such as packet-capture or exfiltration analysis
- `TIMEOUT`: command block exceeded timeout
- `ERROR`: framework/assertion error

## Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python -m docker_lab_validator samples/docker_networking_lab.md --output-dir reports
```

Useful filters:

```bash
python -m docker_lab_validator samples/docker_networking_lab.md --chapter "Docker Networking" --resume
python -m docker_lab_validator samples/docker_networking_lab.md --section "Bridge" --timeout 180
python -m docker_lab_validator samples/docker_networking_lab.md --test-id docker-networking-lab-docker-networking-foundations-bridge-networks-create-a-user-defined-bridge-1
python -m docker_lab_validator samples/docker_networking_lab.md --list-tests
```

## Outputs

The output directory contains:

- `report.html`
- `report.md`
- `report.json`
- `compatibility_report.md`
- `failure_report.md`
- `execution_report.md`
- `checkpoint.json`
- `execution.log`
- `assertions.log`
- `cleanup.log`
- `errors.log`

## Compatibility matrix

| Feature | Native Ubuntu/Debian | macOS Docker Desktop | Rootless Docker |
|---|---|---|---|
| Docker CLI/container/network checks | Supported | Supported through Docker Desktop VM | Supported with rootless limits |
| Docker Compose checks | Supported when compose is installed | Supported | Supported when compose is installed |
| bridge networks | Supported | Supported, VM-backed | Supported with restrictions |
| host networking | Supported | Warning/different behavior | Often unsupported/restricted |
| none networks | Supported | Supported | Supported |
| overlay networks | Supported when swarm/overlay is available | Limited/VM-backed | Limited |
| macvlan/ipvlan | Supported on native Linux | Skipped unsupported or warning | Usually unsupported |
| IPv6 | Requires Docker IPv6 configuration | Limited/VM-backed | Requires rootless IPv6 support |
| iptables/nftables/DOCKER-USER | Actively executed and validated with root | Warning/VM-backed behavior | Attempted, may fail with RCA |
| ip netns/docker0 | Actively executed and validated with root | Warning/VM-backed behavior | Attempted, may fail with RCA |
| tcpdump/conntrack | Actively executed and validated with root | Warning/VM visibility limits | Attempted, may fail with RCA |
| eBPF/Tetragon | Attempted after kernel/BTF/privilege checks | Usually unsupported | Attempted only when prerequisites exist |

## Safety and cleanup

Commands run in a temporary working directory with a configurable timeout. Exit code zero is only the first gate; Docker resources are inspected after execution. The cleanup manager removes inferred containers, networks, volumes, compose stacks, and temporary files. Unsupported platform features are skipped rather than failed.

## Development

```bash
pytest tests/unit
pytest tests/integration
```

## Execution Philosophy

The validator is designed to prove that a lab guide actually works on a disposable Ubuntu VM, not merely parse documentation. `SAFE` and `CAUTION` commands execute automatically. CAUTION commands include apt installs, Docker Swarm operations, firewall modifications, namespace creation, packet capture, and system inspection; they are logged prominently. `BLOCKED` commands are never executed, including root filesystem deletion, reboot/poweroff commands, disk formatting/partitioning, user/group deletion, root password changes, fork bombs, and remote `curl|sh`/`wget|sh` script execution.

For every executed command the framework captures stdout, stderr, exit code, execution time, and risk classification, then performs semantic state assertions. Failures receive root-cause analysis and suggested fixes for common problems such as missing packages, missing privileges, Docker daemon issues, kernel limitations, port conflicts, network conflicts, and command syntax errors.
