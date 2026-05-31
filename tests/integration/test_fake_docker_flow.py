import os
import stat
import textwrap
from pathlib import Path

from docker_lab_validator.models import TestStatus
from docker_lab_validator.platform import PlatformInfo
from docker_lab_validator.runner import ValidationRunner


def write_fake_docker(bin_dir: Path):
    docker = bin_dir / "docker"
    docker.write_text(textwrap.dedent(r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
state = Path(os.environ["FAKE_DOCKER_STATE"])
if state.exists():
    data = json.loads(state.read_text())
else:
    data = {"networks": [], "containers": {}, "volumes": []}

def save(): state.write_text(json.dumps(data))
args = sys.argv[1:]
if args[:2] == ["network", "create"]:
    name = args[-1];
    if name not in data["networks"]: data["networks"].append(name)
    save(); print(name); sys.exit(0)
if args[:2] == ["network", "rm"]:
    name = args[-1]
    if name in data["networks"]: data["networks"].remove(name)
    save(); print(name); sys.exit(0)
if len(args) >= 3 and args[1] == "inspect":
    kind, name = args[0], args[-1]
    ok = (kind == "network" and name in data["networks"]) or (kind == "volume" and name in data["volumes"]) or (kind == "container" and name in data["containers"])
    print("[]" if ok else "not found")
    sys.exit(0 if ok else 1)
if args and args[0] == "inspect":
    name = args[-1]
    running = data["containers"].get(name, {}).get("running", False)
    print(str(running).lower()); sys.exit(0 if name in data["containers"] else 1)
if args and args[0] == "run":
    name = None
    for i, arg in enumerate(args):
        if arg == "--name": name = args[i+1]
        elif arg.startswith("--name="): name = arg.split("=",1)[1]
    if name: data["containers"][name] = {"running": "-d" in args or "--detach" in args}
    save(); print(name or "container"); sys.exit(0)
if args[:1] == ["rm"] or args[:2] == ["container", "rm"]:
    name = args[-1]; data["containers"].pop(name, None); save(); sys.exit(0)
if args[:2] == ["compose", "ps"]:
    print('{"Service":"web","State":"running"}'); sys.exit(0)
if args[:2] == ["compose", "down"]:
    sys.exit(0)
print("fake docker unsupported", args, file=sys.stderr); sys.exit(0)
'''))
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)


def test_network_create_and_remove_with_fake_docker(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"; bin_dir.mkdir()
    state = tmp_path / "state.json"
    write_fake_docker(bin_dir)
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(state))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    doc = tmp_path / "lab.md"
    doc.write_text("""# C
## S
```bash
docker network create int_net
```
```bash
docker network rm int_net
```
""")
    platform = PlatformInfo("linux", True, False, False, False, True, True, {"docker": True})
    runner = ValidationRunner(tmp_path / "out", platform=platform)
    results = runner.run_documents([doc])
    assert [r.status for r in results] == [TestStatus.PASS, TestStatus.PASS]
    assert (tmp_path / "out" / "report.json").exists()
    assert (tmp_path / "out" / "execution.log").exists()
