# Docker Lab Validator

A production-oriented Python framework for validating large hands-on Docker networking and Docker security training guides written in Markdown.

## What it validates

The framework parses every Bash-compatible fenced code block in Markdown and turns it into a test case with:

- unique id
- chapter, section, and subsection context
- command block
- expected behavior extracted from nearby expected/observation/verification sections or inferred from command semantics
- cleanup requirements
- platform requirements

It supports Docker, Docker Compose, bridge/host/none/overlay/macvlan/ipvlan/IPv6/rootless labs, firewall labs, DNS/service-discovery labs, namespace labs, metadata-service exercises, tcpdump/conntrack/iptables/nftables/eBPF/Tetragon exercises, security validation exercises, and cleanup exercises.

## Status model

- `PASS`: commands ran and semantic assertions passed
- `FAIL`: command or semantic assertion failed
- `WARNING`: validation passed but Docker Desktop/rootless/native-Linux behavior may differ
- `SKIPPED_UNSUPPORTED`: platform cannot support a required feature
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
| iptables/nftables/DOCKER-USER | Supported with privileges/tools | Skipped unsupported/warning | Restricted |
| ip netns/docker0 | Supported on native Linux | Skipped unsupported | Restricted |
| tcpdump/conntrack | Supported with privileges/tools | Warning/VM visibility limits | Restricted |
| eBPF/Tetragon | Supported on compatible Linux kernels | Skipped unsupported | Restricted |

## Safety and cleanup

Commands run in a temporary working directory with a configurable timeout. Exit code zero is only the first gate; Docker resources are inspected after execution. The cleanup manager removes inferred containers, networks, volumes, compose stacks, and temporary files. Unsupported platform features are skipped rather than failed.

## Development

```bash
pytest tests/unit
pytest tests/integration
```
