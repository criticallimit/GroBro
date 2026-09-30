from pathlib import Path
import re


def _addon_version() -> str:
    config = Path("config.yaml").read_text(encoding="utf-8")
    match = re.search(r'^version:\s*"([^"]+)"', config, re.MULTILINE)
    assert match
    return match.group(1)


def test_user_facing_release_metadata_matches_addon_version():
    version = _addon_version()
    readme = Path("README.md").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")

    assert f"## Better GroBro {version}" in readme
    assert f"# Better GroBro {version} — Differences from robertzaage/GroBro" in changelog


def test_release_notes_remain_user_focused():
    readme = Path("README.md").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")

    assert "user-relevant differences" in readme
    assert "## User-relevant differences" in changelog
    assert "Runtime architecture" not in readme
    assert "wrapper" not in readme.lower()


def test_runtime_dependencies_have_major_version_bounds():
    requirements = Path("requirements.txt").read_text(encoding="utf-8")

    assert "paho-mqtt>=2.1,<3" in requirements
    assert "crc>=8,<9" in requirements
    assert "pydantic>=2.13,<3" in requirements
