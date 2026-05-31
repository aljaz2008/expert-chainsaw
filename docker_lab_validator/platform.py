from __future__ import annotations

import os
import platform as py_platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PlatformInfo:
    os_name: str
    is_linux: bool
    is_macos: bool
    is_docker_desktop: bool
    is_rootless: bool
    is_root: bool = False
    apt_available: bool = False
    features: dict[str, bool] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    feature_details: dict[str, str] = field(default_factory=dict)

    def supports(self, feature: str) -> bool:
        return self.features.get(feature, False)

    def reason(self, feature: str) -> str:
        return self.feature_details.get(feature, "No detailed reason recorded.")


class PlatformDetector:
    """Detect capabilities for the primary Ubuntu disposable validation VM."""

    INSTALLABLE_WITH_APT = {
        "iptables", "nftables", "ip_netns", "conntrack", "tcpdump", "dig", "nslookup", "curl"
    }

    def detect(self) -> PlatformInfo:
        system = py_platform.system().lower()
        is_root = hasattr(os, "geteuid") and os.geteuid() == 0
        apt_available = shutil.which("apt") is not None or shutil.which("apt-get") is not None
        info = PlatformInfo(
            os_name=system or os.name,
            is_linux=system == "linux",
            is_macos=system == "darwin",
            is_docker_desktop=False,
            is_rootless=False,
            is_root=is_root,
            apt_available=apt_available,
        )
        docker_available = self._docker_available()
        compose_available = self._compose_available()
        linux_privileged = info.is_linux and info.is_root
        info.features.update({
            "docker": docker_available,
            "compose": compose_available,
            "apt": apt_available,
            "pip": shutil.which("pip") is not None or shutil.which("pip3") is not None,
            "iptables": self._tool_or_installable("iptables", info),
            "nftables": self._tool_or_installable("nft", info),
            "ip_netns": linux_privileged and self._tool_or_installable("ip", info),
            "conntrack": linux_privileged and self._tool_or_installable("conntrack", info),
            "docker0": info.is_linux and docker_available,
            "systemctl": info.is_linux and shutil.which("systemctl") is not None,
            "tcpdump": linux_privileged and self._tool_or_installable("tcpdump", info),
            "ebpf": self._ebpf_possible(info),
            "tetragon": self._tetragon_possible(info),
            "host_network": info.is_linux and docker_available,
            "macvlan": info.is_linux and docker_available and linux_privileged,
            "ipvlan": info.is_linux and docker_available and linux_privileged,
            "overlay": docker_available,
            "rootless": True,  # rootless labs should be attempted; failures receive RCA.
            "metadata_service": True,  # attempt; environment-specific assertions may become manual/fail.
            "ipv6": docker_available,  # attempt IPv6 labs; Docker daemon state is validated by commands/assertions.
            "dig": self._tool_or_installable("dig", info),
            "nslookup": self._tool_or_installable("nslookup", info),
            "curl": self._tool_or_installable("curl", info),
        })
        self._enrich_docker_info(info)
        self._populate_feature_details(info)
        if info.is_docker_desktop:
            info.warnings.append("Docker Desktop uses a VM; host networking, docker0, packet capture, and firewall behavior can differ from native Linux.")
        if info.is_rootless:
            info.warnings.append("Rootless Docker may restrict privileged networking, host networking, and low port publishing.")
        if info.is_linux and not info.is_root:
            info.warnings.append("Not running as root; CAUTION Linux networking commands may fail with missing privilege diagnostics.")
        return info

    def _tool_or_installable(self, tool: str, info: PlatformInfo) -> bool:
        return shutil.which(tool) is not None or (info.is_linux and info.apt_available)

    def _run(self, args: list[str], timeout: int = 8) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.SubprocessError):
            return None

    def _docker_available(self) -> bool:
        result = self._run(["docker", "version", "--format", "{{.Server.Version}}"])
        return bool(result and result.returncode == 0 and result.stdout.strip())

    def _compose_available(self) -> bool:
        result = self._run(["docker", "compose", "version"])
        if result and result.returncode == 0:
            return True
        legacy = self._run(["docker-compose", "version"])
        return bool(legacy and legacy.returncode == 0)

    def _ebpf_possible(self, info: PlatformInfo) -> bool:
        if not info.is_linux or not info.is_root:
            return False
        btf = Path("/sys/kernel/btf/vmlinux").exists()
        bpf_fs = Path("/sys/fs/bpf").exists()
        kernel = py_platform.release()
        return btf and bpf_fs and bool(kernel)

    def _tetragon_possible(self, info: PlatformInfo) -> bool:
        return info.is_linux and info.is_root and (self._ebpf_possible(info) or shutil.which("tetragon") is not None or shutil.which("tetra") is not None)

    def _enrich_docker_info(self, info: PlatformInfo) -> None:
        result = self._run(["docker", "info", "--format", "{{.OperatingSystem}}|{{.SecurityOptions}}|{{.Name}}"])
        if not result or result.returncode != 0:
            return
        data = result.stdout.lower()
        info.is_docker_desktop = "docker desktop" in data
        info.is_rootless = "rootless" in data

    def _populate_feature_details(self, info: PlatformInfo) -> None:
        for feature, supported in info.features.items():
            if supported:
                info.feature_details[feature] = "Available or installable in the disposable Ubuntu validation VM."
            else:
                if feature in {"ebpf", "tetragon"}:
                    info.feature_details[feature] = "Requires Linux root privileges plus BTF/BPF filesystem or installed Tetragon tooling."
                elif feature in {"ip_netns", "conntrack", "tcpdump", "macvlan", "ipvlan"}:
                    info.feature_details[feature] = "Requires native Linux root privileges."
                elif feature in {"docker", "compose"}:
                    info.feature_details[feature] = "Docker Engine/Compose is not reachable from this process."
                else:
                    info.feature_details[feature] = "Not detected on this platform."
