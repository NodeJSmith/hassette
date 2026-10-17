import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "tools" / "release" / "bump_addon.py"
_spec = importlib.util.spec_from_file_location("bump_addon", SCRIPT_PATH)
assert _spec is not None
assert _spec.loader is not None
bump_addon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bump_addon)

REPOSITORY = "NodeJSmith/hassette"
CONFIG = """# Settled by hassette's design (decision numbers in comments).
name: Hassette
version: "0.57.0"
slug: hassette
image: ghcr.io/nodejsmith/hassette-addon
options:
  log_level: info
"""
CHANGELOG = """# Changelog

Each version matches a hassette release of the same number.

## 0.57.0

- [hassette 0.57.0 release notes](https://github.com/NodeJSmith/hassette/releases/tag/v0.57.0)
"""


@pytest.fixture
def addon_dir(tmp_path: Path) -> Path:
    (tmp_path / "hassette").mkdir()
    (tmp_path / "hassette" / "config.yaml").write_text(CONFIG)
    (tmp_path / "hassette" / "CHANGELOG.md").write_text(CHANGELOG)
    return tmp_path


def read(addon_dir: Path, name: str) -> str:
    return (addon_dir / "hassette" / name).read_text()


def test_stable_release_bumps_version_and_prepends_changelog_entry(addon_dir: Path) -> None:
    outputs = bump_addon.run("v0.58.0", addon_dir, REPOSITORY)

    assert outputs == {
        "action": "bump",
        "version": "0.58.0",
        "image": "ghcr.io/nodejsmith/hassette-addon",
        "current": "0.57.0",
    }
    assert read(addon_dir, "config.yaml") == CONFIG.replace('version: "0.57.0"', 'version: "0.58.0"')
    assert read(addon_dir, "CHANGELOG.md") == CHANGELOG.replace(
        "## 0.57.0",
        "## 0.58.0\n\n- [hassette 0.58.0 release notes]"
        "(https://github.com/NodeJSmith/hassette/releases/tag/v0.58.0)\n\n## 0.57.0",
    )


def test_minor_version_compares_numerically_not_lexically(addon_dir: Path) -> None:
    (addon_dir / "hassette" / "config.yaml").write_text(CONFIG.replace("0.57.0", "0.9.0"))

    assert bump_addon.run("v0.10.0", addon_dir, REPOSITORY)["action"] == "bump"


def test_equal_version_is_a_noop_that_leaves_files_untouched(addon_dir: Path) -> None:
    outputs = bump_addon.run("v0.57.0", addon_dir, REPOSITORY)

    assert outputs["action"] == "noop"
    assert read(addon_dir, "config.yaml") == CONFIG
    assert read(addon_dir, "CHANGELOG.md") == CHANGELOG


@pytest.mark.parametrize("tag", ["v0.58.0rc1", "v0.58.0.dev1", "v0.58.0a2", "v0.58.0.post1"])
def test_non_stable_tag_is_skipped(addon_dir: Path, tag: str) -> None:
    outputs = bump_addon.run(tag, addon_dir, REPOSITORY)

    assert outputs["action"] == "skip"
    assert read(addon_dir, "config.yaml") == CONFIG


def test_lower_version_is_refused_and_main_exits_nonzero(addon_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = bump_addon.main(["--tag", "v0.56.3", "--addon-dir", str(addon_dir), "--release-repo", REPOSITORY])

    assert exit_code == 1
    assert "refusing to downgrade" in capsys.readouterr().err
    assert read(addon_dir, "config.yaml") == CONFIG


def test_nested_version_keys_are_not_mistaken_for_the_addon_version(addon_dir: Path) -> None:
    (addon_dir / "hassette" / "config.yaml").write_text(CONFIG + "schema:\n  version: str\n")

    assert bump_addon.run("v0.58.0", addon_dir, REPOSITORY)["current"] == "0.57.0"


def test_missing_version_line_fails(addon_dir: Path) -> None:
    (addon_dir / "hassette" / "config.yaml").write_text(CONFIG.replace('version: "0.57.0"\n', ""))

    with pytest.raises(bump_addon.BumpError, match="exactly one top-level `version:`"):
        bump_addon.run("v0.58.0", addon_dir, REPOSITORY)


def test_changelog_without_entries_gets_the_first_one_appended() -> None:
    result = bump_addon.add_changelog_entry("# Changelog\n", "0.58.0", "https://example.test/v0.58.0")

    assert result == "# Changelog\n\n## 0.58.0\n\n- [hassette 0.58.0 release notes](https://example.test/v0.58.0)\n"


def test_main_writes_delimited_github_output(addon_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_file = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    exit_code = bump_addon.main(["--tag", "v0.58.0", "--addon-dir", str(addon_dir), "--release-repo", REPOSITORY])

    assert exit_code == 0
    assert parse_github_output(output_file.read_text()) == {
        "action": "bump",
        "version": "0.58.0",
        "image": "ghcr.io/nodejsmith/hassette-addon",
        "current": "0.57.0",
    }


def parse_github_output(text: str) -> dict[str, str]:
    """Parse `key<<delimiter` / value / `delimiter` blocks the way the Actions runner does."""
    outputs: dict[str, str] = {}
    lines = iter(text.splitlines())
    for header in lines:
        key, delimiter = header.split("<<", 1)
        value_lines = []
        for line in lines:
            if line == delimiter:
                break
            value_lines.append(line)
        outputs[key] = "\n".join(value_lines)
    return outputs
