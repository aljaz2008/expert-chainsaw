from __future__ import annotations

import re
from pathlib import Path
from .models import TestCase, PlatformRequirement, safe_id

FENCE_RE = re.compile(r"^(```|~~~)\s*([^`]*)\s*$")
EXPECTED_HEADINGS = {"expected", "expected behavior", "expected result", "expected results", "observation", "observations", "verify", "verification"}
CLEANUP_HEADINGS = {"cleanup", "clean up", "teardown", "reset"}
THEORY_HEADINGS = {"theory", "background", "overview", "explanation"}

FEATURE_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\biptables\b|DOCKER-USER", re.I), "iptables", "iptables/DOCKER-USER should be actively validated on the Ubuntu VM"),
    (re.compile(r"\bnft\b|\bnftables\b", re.I), "nftables", "nftables should be actively validated on the Ubuntu VM"),
    (re.compile(r"\bip\s+netns\b|/var/run/netns", re.I), "ip_netns", "network namespaces should be actively validated on the Ubuntu VM"),
    (re.compile(r"\bconntrack\b", re.I), "conntrack", "conntrack should be actively validated on the Ubuntu VM"),
    (re.compile(r"\bdocker0\b", re.I), "docker0", "docker0 bridge exists on native Linux but not inside Docker Desktop hosts"),
    (re.compile(r"\bsystemctl\b", re.I), "systemctl", "systemd is not available on all systems"),
    (re.compile(r"\btcpdump\b", re.I), "tcpdump", "packet capture should be actively validated on the Ubuntu VM"),
    (re.compile(r"\bebpf\b|\bbpftrace\b|\bbpftool\b", re.I), "ebpf", "eBPF should be attempted after checking kernel/BTF/privileges"),
    (re.compile(r"\btetragon\b", re.I), "tetragon", "Tetragon should be attempted when eBPF prerequisites are present"),
    (re.compile(r"--network\s+host|network_mode:\s*host", re.I), "host_network", "host networking differs on Docker Desktop and native Linux"),
    (re.compile(r"\bmacvlan\b", re.I), "macvlan", "macvlan requires native Linux networking support"),
    (re.compile(r"\bipvlan\b", re.I), "ipvlan", "ipvlan requires native Linux networking support"),
    (re.compile(r"\boverlay\b|docker\s+swarm", re.I), "overlay", "overlay networks require swarm/overlay capability"),
    (re.compile(r"\brootless\b|dockerd-rootless", re.I), "rootless", "rootless Docker must be installed and active"),
    (re.compile(r"169\.254\.169\.254|metadata", re.I), "metadata_service", "metadata service tests are cloud/platform dependent"),
    (re.compile(r"\bAAAA\b|--ipv6|enable_ipv6|fixed-cidr-v6", re.I), "ipv6", "IPv6 Docker networking should be actively validated"),
    (re.compile(r"\bapt(?:-get)?\s+(?:update|install)\b", re.I), "apt", "apt is expected on the Ubuntu validation VM"),
    (re.compile(r"\bpip3?\s+install\b", re.I), "pip", "pip/pip3 is needed for Python package setup commands"),
    (re.compile(r"\bcurl\b", re.I), "curl", "curl is needed for HTTP validation commands"),
    (re.compile(r"\bdig\b", re.I), "dig", "dig is needed for DNS validation commands"),
    (re.compile(r"\bnslookup\b", re.I), "nslookup", "nslookup is needed for DNS validation commands"),
]


class MarkdownLabParser:
    """Parse Markdown lab guides into executable test cases."""

    def parse_file(self, path: str | Path) -> list[TestCase]:
        file_path = Path(path)
        return self.parse_text(file_path.read_text(encoding="utf-8"), source_file=str(file_path))

    def parse_text(self, text: str, source_file: str = "<memory>") -> list[TestCase]:
        lines = text.splitlines()
        headings: dict[int, str] = {}
        cases: list[TestCase] = []
        i = 0
        block_index = 0
        while i < len(lines):
            line = lines[i]
            heading = self._parse_heading(line)
            if heading:
                level, title = heading
                headings[level] = title
                for old in list(headings):
                    if old > level:
                        del headings[old]
                i += 1
                continue
            fence = FENCE_RE.match(line)
            if fence and self._is_bash_fence(fence.group(2)):
                fence_token = fence.group(1)
                start_line = i + 1
                i += 1
                block_lines: list[str] = []
                while i < len(lines) and not lines[i].startswith(fence_token):
                    block_lines.append(lines[i])
                    i += 1
                command_block = "\n".join(block_lines).strip()
                if i < len(lines):
                    i += 1
                if command_block:
                    block_index += 1
                    chapter = headings.get(1) or headings.get(2) or "Document"
                    section = headings.get(2) if headings.get(1) else headings.get(3, "")
                    subsection = headings.get(3, "") if headings.get(1) else headings.get(4, "")
                    base = safe_id(f"{Path(source_file).stem}-{chapter}-{section}-{subsection}-{block_index}")
                    cases.append(TestCase(
                        id=base,
                        chapter=chapter,
                        section=section or chapter,
                        subsection=subsection,
                        command_block=command_block,
                        expected_behavior=self._nearby_expected(lines, i),
                        cleanup_requirements=self._infer_cleanup(command_block, lines, i),
                        platform_requirements=self._infer_platform_requirements(command_block),
                        source_file=source_file,
                        line_start=start_line,
                        metadata={"block_index": block_index},
                    ))
                continue
            i += 1
        return cases

    def _parse_heading(self, line: str) -> tuple[int, str] | None:
        stripped = line.strip()
        if not stripped.startswith("#"):
            return None
        hashes = len(stripped) - len(stripped.lstrip("#"))
        if hashes > 6 or len(stripped) <= hashes or stripped[hashes] != " ":
            return None
        return hashes, stripped[hashes:].strip()

    def _is_bash_fence(self, info: str) -> bool:
        lang = info.strip().split()[0].lower() if info.strip() else ""
        return lang in {"bash", "sh", "shell", "console", "zsh"}

    def _nearby_expected(self, lines: list[str], index: int) -> str:
        snippets: list[str] = []
        for j in range(index, min(len(lines), index + 18)):
            heading = self._parse_heading(lines[j])
            if heading:
                normalized = heading[1].strip().lower().rstrip(":")
                if normalized in EXPECTED_HEADINGS:
                    k = j + 1
                    while k < len(lines):
                        if self._parse_heading(lines[k]) or FENCE_RE.match(lines[k]):
                            break
                        if lines[k].strip():
                            snippets.append(lines[k].strip())
                        k += 1
                    break
                if normalized in THEORY_HEADINGS:
                    break
            elif lines[j].lower().strip().startswith(("expected:", "verify:", "observe:")):
                snippets.append(lines[j].strip())
        return "\n".join(snippets) or "Derived from command semantics and post-command resource assertions."

    def _infer_cleanup(self, command_block: str, lines: list[str], index: int) -> list[str]:
        cleanups: set[str] = set()
        patterns = [
            (r"docker\s+(?:container\s+)?run(?:\s|$).*?(?:--name\s+|--name=)([\w.-]+)", "container:{0}"),
            (r"docker\s+network\s+create(?:\s+\S+)*\s+([\w.-]+)\s*$", "network:{0}"),
            (r"docker\s+volume\s+create(?:\s+\S+)*\s+([\w.-]+)\s*$", "volume:{0}"),
            (r"docker\s+compose\s+.*\bup\b", "compose_stack"),
            (r"docker-compose\s+.*\bup\b", "compose_stack"),
        ]
        for regex, template in patterns:
            for match in re.finditer(regex, command_block, re.I | re.M):
                value = match.group(1) if match.groups() else ""
                cleanups.add(template.format(value))
        for j in range(index, min(len(lines), index + 25)):
            heading = self._parse_heading(lines[j])
            if heading and heading[1].strip().lower().rstrip(":") in CLEANUP_HEADINGS:
                cleanups.add("documented_cleanup_section")
                break
        return sorted(cleanups)

    def _infer_platform_requirements(self, command_block: str) -> list[PlatformRequirement]:
        requirements: dict[str, PlatformRequirement] = {}
        if re.search(r"\bdocker\b", command_block):
            requirements["docker"] = PlatformRequirement("docker", "Docker CLI and daemon are required")
        if re.search(r"docker\s+compose|docker-compose", command_block):
            requirements["compose"] = PlatformRequirement("compose", "Docker Compose is required")
        for pattern, feature, reason in FEATURE_PATTERNS:
            if pattern.search(command_block):
                requirements[feature] = PlatformRequirement(feature, reason)
        return list(requirements.values())
