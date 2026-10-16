from pathlib import Path

from watchfiles import Change

from hassette.core.file_watcher import collapse_changed_paths


def test_collapse_changed_paths_resolves_and_dedupes(tmp_path: Path) -> None:
    """Paths are resolved, so the same file reached two ways is reported once."""
    target = tmp_path / "app.py"
    changes = {(Change.modified, str(target)), (Change.added, str(tmp_path / "sub" / ".." / "app.py"))}

    assert collapse_changed_paths(changes) == {target.resolve()}


def test_collapse_changed_paths_skips_children_of_a_seen_directory(tmp_path: Path) -> None:
    """A file whose parent directory already changed is folded into the directory's change."""
    apps_dir = tmp_path / "apps"
    changes = [(Change.added, str(apps_dir)), (Change.added, str(apps_dir / "new_app.py"))]

    assert collapse_changed_paths(changes) == {apps_dir.resolve()}
