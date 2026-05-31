from __future__ import annotations

import os
import platform as py_platform
import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass
class PlatformInfo:
    os_name: str
    is_linux: bool
    is_macos: bool
    is_docker_desktop: bool
    is_rootless: bool
    features: dict[str, bool] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def supports(self, feature: str) -> bool:
        return self.features.get(feature, False)


class PlatformDetector:
    def detect(self) -> PlatformInfo:
        system = py_platform.system().lower()
        info = PlatformInfo(
            os_name=system or os.name,
            is_linux=system == "linux",
            is_macos=system == "darwin",
            is_docker_desktop=False,
            is_rootless=False,
        )
        info.features.update({
            "docker": self._docker_available(),
            "compose": self._compose_available(),
            "iptables": system == "linux" and shutil.which("iptables") is not None,
            "nftables": system == "linux" and shutil.which("nft") is not None,
            "ip_netns": system == "linux" and shutil.which("ip") is not None and os.geteuid() == 0 if hasattr(os, "geteuid") else False,
            "conntrack": system == "linux" and shutil.which("conntrack") is not None,
            "docker0": system == "linux" and os.path.exists("/sys/class/net/docker0"),
            "systemctl": system == "linux" and shutil.which("systemctl") is not None,
            "tcpdump": shutil.which("tcpdump") is not None,
            "ebpf": system == "linux" and os.path.exists("/sys/fs/bpf"),
            "tetragon": shutil.which("tetragon") is not None or shutil.which("tetra") is not None,
            "host_network": system == "linux",
            "macvlan": system == "linux",
            "ipvlan": system == "linux",
            "overlay": self._docker_available(),
            "rootless": False,
            "metadata_service": False,
            "ipv6": self._docker_ipv6_enabled(),
        })
        self._enrich_docker_info(info)
        if info.is_docker_desktop:
            info.warnings.append("Docker Desktop uses a VM; host networking, docker0, packet capture, and firewall behavior can differ from native Linux.")
            info.features["docker0"] = False
            info.features["ip_netns"] = False
        if info.is_rootless:
            info.features["rootless"] = True
            info.warnings.append("Rootless Docker may restrict privileged networking, host networking, and low port publishing.")
        return info

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

    def _docker_ipv6_enabled(self) -> bool:
        result = self._run(["docker", "info", "--format", "{{json .IPv6}}"])
        return bool(result and result.returncode == 0 and "true" in result.stdout.lower())

    def _enrich_docker_info(self, info: PlatformInfo) -> None:
        result = self._run(["docker", "info", "--format", "{{.OperatingSystem}}|{{.SecurityOptions}}|{{.Name}}"])
        if not result or result.returncode != 0:
            return
        data = result.stdout.lower()
        info.is_docker_desktop = "docker desktop" in data
        info.is_rootless = "rootless" in data
