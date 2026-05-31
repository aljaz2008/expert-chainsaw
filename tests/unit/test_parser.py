from docker_lab_validator.parser import MarkdownLabParser


def test_parser_turns_each_bash_block_into_test_case():
    text = """# Chapter One
## Networks
### Create
```bash
docker network create demo_net
```
#### Expected behavior
Network exists.
```bash
docker network rm demo_net
```
"""
    tests = MarkdownLabParser().parse_text(text, "lab.md")
    assert len(tests) == 2
    assert tests[0].chapter == "Chapter One"
    assert tests[0].section == "Networks"
    assert tests[0].subsection == "Create"
    assert "Network exists" in tests[0].expected_behavior
    assert tests[0].id != tests[1].id
    assert any(req.feature == "docker" for req in tests[0].platform_requirements)
    assert "network:demo_net" in tests[0].cleanup_requirements


def test_parser_detects_linux_only_features():
    tests = MarkdownLabParser().parse_text("""# C
## S
```bash
iptables -S DOCKER-USER
ip netns list
conntrack -L
```
""")
    features = {req.feature for req in tests[0].platform_requirements}
    assert {"iptables", "ip_netns", "conntrack"}.issubset(features)
