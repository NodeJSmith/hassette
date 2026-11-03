"""Tests for tools/frontend/attach_pr_screenshots.py.

Real git plumbing against a throwaway repo and a bare "origin": the tool's whole contract is what
lands in the object store, on the remote, and in the local refs, index and worktree, so mocking
git would only re-assert the mock. The remote's URL is a GitHub URL (the tool derives the link's
``owner/repo`` from it) with ``pushInsteadOf`` routing pushes to the local bare repo.
"""

import subprocess
from pathlib import Path

import pytest
from attach_pr_screenshots import (
    ADD_MESSAGE,
    REMOVE_MESSAGE,
    SCREENSHOT_DIR,
    AttachError,
    attach,
    github_repo_slug,
    main,
)
from check_pr_screenshots import branch_scoped_raw_prefixes, evaluate

from .conftest import GitRepo

GITHUB_URL = "https://github.com/NodeJSmith/hassette.git"
BRANCH = "feature"


def run_git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def bare(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The bare repo standing in for origin, outside the working repo's directory."""
    return tmp_path_factory.mktemp("remote") / "origin.git"


@pytest.fixture
def pr_repo(git_repo: GitRepo, bare: Path) -> GitRepo:
    """A repo on a pushed feature branch with an upstream, its origin a bare repo behind a GitHub URL."""
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True)
    run_git(git_repo.root, "remote", "add", "origin", GITHUB_URL)
    run_git(git_repo.root, "config", f"url.{bare}.pushInsteadOf", GITHUB_URL)
    git_repo.write(".gitignore", "*.png\n")
    git_repo.write("app.py", "print('hi')\n")
    git_repo.commit("initial")
    run_git(git_repo.root, "checkout", "-q", "-b", BRANCH)
    git_repo.write("app.py", "print('feature')\n")
    git_repo.commit("feature work")
    run_git(git_repo.root, "push", "-q", "-u", "origin", BRANCH)
    return git_repo


@pytest.fixture
def images(tmp_path_factory: pytest.TempPathFactory) -> list[Path]:
    shots = tmp_path_factory.mktemp("shots")
    paths = [shots / "apps-pet_feeder.png", shots / "apps list.png"]
    for i, path in enumerate(paths):
        path.write_bytes(b"\x89PNG fake " + bytes([i]))
    return paths


def bare_branch_tip(bare: Path) -> str:
    return run_git(bare, "rev-parse", f"refs/heads/{BRANCH}")


def test_attach_pushes_add_then_remove_and_leaves_the_tree_unchanged(
    pr_repo: GitRepo, images: list[Path], bare: Path
) -> None:
    pr_repo.write("app.py", "uncommitted edit\n")
    head_before = run_git(pr_repo.root, "rev-parse", "HEAD")
    tree_before = run_git(pr_repo.root, "rev-parse", "HEAD^{tree}")
    status_before = run_git(pr_repo.root, "status", "--porcelain")

    markdown = attach(pr_repo.root, images)

    remove_sha = run_git(pr_repo.root, "rev-parse", "HEAD")
    add_sha = run_git(pr_repo.root, "rev-parse", "HEAD^")
    assert run_git(pr_repo.root, "rev-parse", "HEAD~2") == head_before
    assert run_git(pr_repo.root, "log", "-1", "--format=%s", add_sha) == ADD_MESSAGE
    assert run_git(pr_repo.root, "log", "-1", "--format=%s", remove_sha) == REMOVE_MESSAGE
    assert run_git(pr_repo.root, "rev-parse", "HEAD^{tree}") == tree_before
    assert bare_branch_tip(bare) == remove_sha
    assert run_git(pr_repo.root, "status", "--porcelain") == status_before
    assert (pr_repo.root / "app.py").read_text() == "uncommitted edit\n"

    for image in images:
        stored = subprocess.run(
            ["git", "show", f"{add_sha}:{SCREENSHOT_DIR}/{image.name}"],
            cwd=pr_repo.root,
            check=True,
            capture_output=True,
        ).stdout
        assert stored == image.read_bytes()
    assert f"/NodeJSmith/hassette/{add_sha}/{SCREENSHOT_DIR}/apps%20list.png" in markdown


def test_markdown_satisfies_the_screenshot_check(pr_repo: GitRepo, images: list[Path]) -> None:
    markdown = attach(pr_repo.root, images)

    assert markdown.startswith("### Screenshots\n")
    assert markdown.count("![") == len(images)
    assert branch_scoped_raw_prefixes(markdown) == []
    assert evaluate(["frontend/src/App.tsx"], markdown, []) == (True, True)


def test_main_prints_the_markdown(
    pr_repo: GitRepo, images: list[Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(pr_repo.root)

    assert main([str(p) for p in images]) == 0

    assert capsys.readouterr().out.startswith("### Screenshots\n")


def test_rejected_push_leaves_the_local_branch_alone(
    pr_repo: GitRepo, images: list[Path], bare: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    other = tmp_path_factory.mktemp("other") / "clone"
    subprocess.run(["git", "clone", "-q", "-b", BRANCH, str(bare), str(other)], check=True, capture_output=True)
    run_git(
        other, "-c", "user.email=t@e.com", "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "remote moved"
    )
    run_git(other, "push", "-q", "origin", BRANCH)
    head_before = run_git(pr_repo.root, "rev-parse", "HEAD")

    with pytest.raises(AttachError, match="pull it and rerun"):
        attach(pr_repo.root, images)

    assert run_git(pr_repo.root, "rev-parse", "HEAD") == head_before


def test_branch_without_upstream_is_refused(pr_repo: GitRepo, images: list[Path]) -> None:
    run_git(pr_repo.root, "checkout", "-q", "-b", "unpushed")

    with pytest.raises(AttachError, match="no upstream"):
        attach(pr_repo.root, images)


def test_detached_head_is_refused(pr_repo: GitRepo, images: list[Path]) -> None:
    run_git(pr_repo.root, "checkout", "-q", "--detach")

    with pytest.raises(AttachError, match="detached"):
        attach(pr_repo.root, images)


def test_duplicate_filenames_are_refused(
    pr_repo: GitRepo, images: list[Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    twin = tmp_path_factory.mktemp("elsewhere") / images[0].name
    twin.write_bytes(b"other")

    with pytest.raises(AttachError, match="share the filename"):
        attach(pr_repo.root, [images[0], twin])


def test_missing_image_is_refused(pr_repo: GitRepo, bare: Path) -> None:
    with pytest.raises(AttachError, match="not a file"):
        attach(pr_repo.root, [pr_repo.root / "nope.png"])

    assert bare_branch_tip(bare) == run_git(pr_repo.root, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:NodeJSmith/hassette.git",
        "ssh://git@github.com/NodeJSmith/hassette.git",
        "https://github.com/NodeJSmith/hassette.git",
        "https://github.com/NodeJSmith/hassette",
        "https://github.com/NodeJSmith/hassette/",
    ],
)
def test_github_repo_slug(url: str) -> None:
    assert github_repo_slug(url) == "NodeJSmith/hassette"


def test_non_github_remote_is_refused() -> None:
    with pytest.raises(AttachError, match="not a GitHub repository"):
        github_repo_slug("https://gitlab.com/NodeJSmith/hassette.git")
