#!/usr/bin/env python3
"""Host PR screenshots on the current branch without merging them, and print the Markdown that embeds them.

PR visual evidence (see ``check_pr_screenshots.py``) needs image URLs that keep working after the
PR merges and its branch is deleted. This tool pushes two commits to the current branch: one adds
the images under ``.pr-screenshots/``, the next removes them. It then prints a ``### Screenshots``
block linking each image at the add commit's full SHA.

- The squash merge drops both commits, so the images never reach the default branch or ordinary
  clones.
- GitHub keeps every PR's commits under ``refs/pull/<N>/head``, so the SHA-pinned links outlive
  the branch.
- The commits are built with git plumbing against a temporary index. The branch's tree, the
  worktree and the index are left as they were, and ``*.png`` being gitignored doesn't matter.

The tool doesn't edit the PR body. Paste the printed block into it yourself, so the body's
structure and any ``BREAKING CHANGE:`` footer stay under your control.

Usage:
    uv run python tools/frontend/attach_pr_screenshots.py shots/apps.png shots/apps-pet_feeder.png

The current branch must already be pushed with an upstream (``git push -u``) and not be behind it.
The commits go to that upstream, which is assumed to be where the PR's branch lives.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

SCREENSHOT_DIR = ".pr-screenshots"
RAW_BASE_URL = "https://raw.githubusercontent.com"
GITHUB_REMOTE_RE = re.compile(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
ADD_MESSAGE = "chore: add PR screenshots"
REMOVE_MESSAGE = "chore: remove PR screenshots"
GIT_TIMEOUT_SECONDS = 120


class AttachError(Exception):
    """A precondition failed or a git step was refused; the message says which."""


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    """Run a git command in `repo` and return its stripped stdout, raising AttachError on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
            env=env,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise AttachError(f"git {' '.join(args)} failed: {detail}") from exc
    return result.stdout.strip()


def github_repo_slug(remote_url: str) -> str:
    """Return ``owner/repo`` for a GitHub remote URL (SSH or HTTPS), raising AttachError otherwise."""
    match = GITHUB_REMOTE_RE.search(remote_url)
    if not match:
        raise AttachError(f"remote URL {remote_url!r} is not a GitHub repository")
    return f"{match.group(1)}/{match.group(2)}"


def validate_images(images: list[Path]) -> None:
    """Raise AttachError if an image is missing or two images share a filename."""
    seen: dict[str, Path] = {}
    for image in images:
        if not image.is_file():
            raise AttachError(f"{image} is not a file")
        if image.name in seen:
            raise AttachError(f"{image} and {seen[image.name]} share the filename {image.name}")
        seen[image.name] = image


def build_screenshot_commits(repo: Path, head: str, images: list[Path]) -> tuple[str, str]:
    """Create the add and remove commits on top of `head`, returning ``(add_sha, remove_sha)``.

    The remove commit's tree is `head`'s own tree, so moving the branch to it leaves the worktree
    and index matching. A temporary index keeps the real one untouched.
    """
    with tempfile.TemporaryDirectory(prefix="hassette-pr-screenshots-") as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git(repo, "read-tree", head, env=env)
        for image in images:
            blob = git(repo, "hash-object", "-w", "--", str(image.resolve()))
            git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{SCREENSHOT_DIR}/{image.name}", env=env)
        add_tree = git(repo, "write-tree", env=env)
    add_sha = git(repo, "commit-tree", add_tree, "-p", head, "-m", ADD_MESSAGE)
    remove_sha = git(repo, "commit-tree", f"{head}^{{tree}}", "-p", add_sha, "-m", REMOVE_MESSAGE)
    return add_sha, remove_sha


def screenshots_markdown(slug: str, add_sha: str, images: list[Path]) -> str:
    """Render the ``### Screenshots`` block, each image linked at `add_sha`."""
    lines = ["### Screenshots", ""]
    for image in images:
        url = f"{RAW_BASE_URL}/{slug}/{add_sha}/{SCREENSHOT_DIR}/{urllib.parse.quote(image.name)}"
        lines += [f"![{image.stem}]({url})", ""]
    return "\n".join(lines).rstrip() + "\n"


def attach(repo: Path, images: list[Path]) -> str:
    """Push the screenshot commits to the current branch's upstream and return the Markdown block."""
    validate_images(images)
    try:
        branch = git(repo, "symbolic-ref", "--short", "HEAD")
    except AttachError as exc:
        raise AttachError("HEAD is detached; check out the PR's branch first") from exc
    try:
        remote = git(repo, "config", f"branch.{branch}.remote")
        merge_ref = git(repo, "config", f"branch.{branch}.merge")
    except AttachError as exc:
        raise AttachError(f"branch {branch!r} has no upstream; push it first: git push -u origin {branch}") from exc
    slug = github_repo_slug(git(repo, "remote", "get-url", remote))

    head = git(repo, "rev-parse", "HEAD")
    add_sha, remove_sha = build_screenshot_commits(repo, head, images)
    try:
        git(repo, "push", remote, f"{remove_sha}:{merge_ref}")
    except AttachError as exc:
        raise AttachError(f"{exc}\nIf the remote branch moved ahead, pull it and rerun.") from exc
    markdown = screenshots_markdown(slug, add_sha, images)
    # Move the local branch to the pushed tip so it isn't left behind its upstream. The remove
    # commit's tree is HEAD's own, so the worktree and index still match.
    try:
        git(repo, "update-ref", f"refs/heads/{branch}", remove_sha, head)
    except AttachError as exc:
        raise AttachError(
            f"{exc}\nThe screenshot commits were pushed, but {branch!r} moved locally meanwhile; "
            f"run `git pull` to catch up. The block to paste:\n\n{markdown}"
        ) from exc
    return markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("images", nargs="+", type=Path, help="image files to attach")
    args = parser.parse_args(argv)

    try:
        repo = Path(git(Path.cwd(), "rev-parse", "--show-toplevel"))
        markdown = attach(repo, args.images)
    except AttachError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(markdown, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
