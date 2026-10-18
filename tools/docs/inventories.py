"""Vendored ``objects.inv`` inventories for mkdocstrings cross-references.

mkdocstrings fetches external inventories at build time with no retry or fallback, and a failed fetch is
an ERROR that aborts ``mkdocs build --strict``. Read the Docs rate-limits its own builders when they fetch
inventories hosted on Read the Docs (whenever, aiohttp), so a 429 there used to fail the required docs check
on PRs that changed nothing in the docs. Committed copies make the build independent of those hosts.

As an mkdocs hook (``hooks:`` in ``mkdocs.yml``), this sets the python handler's ``inventories`` to the
committed files, each with a ``base_url`` so cross-references still link to the live docs sites.
``INVENTORIES`` is the single source of the list; ``mkdocs.yml`` doesn't repeat it.

Run directly to re-download every committed copy from upstream (to add an inventory, add it to
``INVENTORIES`` first):

    uv run python tools/docs/inventories.py

A stale copy misses links to symbols added upstream and can keep links to anchors upstream has since
removed, and neither fails the build. ``docs-inventory-drift.yml`` checks for that weekly by running this
script with ``--check``, which downloads every inventory, compares it to the committed copy, and prints the
names that differ. On drift the workflow files a tracking issue for the refresh above.
"""

import argparse
import hashlib
import http.client
import sys
import urllib.request
from pathlib import Path
from typing import Any

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.exceptions import PluginError
from mkdocs.plugins import event_priority

INVENTORY_DIR = Path(__file__).resolve().parent / "inventories"
# Name of the committed file (without .inv) -> docs root that the inventory's relative URIs resolve against.
INVENTORIES = {
    "python": "https://docs.python.org/3/",
    "pydantic": "https://docs.pydantic.dev/latest/",
    "aiohttp": "https://docs.aiohttp.org/en/stable/",
    "whenever": "https://whenever.readthedocs.io/en/latest/",
}
DOWNLOAD_TIMEOUT_SECONDS = 30
# --check exit code when at least one download failed: the drifted list covers only the inventories fetched.
INCOMPLETE_CHECK_EXIT_CODE = 3


def inventory_path(name: str) -> Path:
    return INVENTORY_DIR / f"{name}.inv"


def inventory_url(name: str) -> str:
    """Return a ``file://`` URL for a committed inventory, with its content hash as the fragment.

    mkdocs caches inventory downloads in the user cache directory for a day, keyed by URL, and would otherwise
    keep serving a copy of the old file after a refresh, or after the file is deleted. urllib ignores the
    fragment when opening the file, so the hash only changes the cache key.
    """
    path = inventory_path(name)
    if not path.is_file():
        raise PluginError(f"Missing vendored inventory {path}. Run: uv run python tools/docs/inventories.py")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{path.as_uri()}#sha256={digest}"


# Runs before mkdocstrings' own on_config, which reads the handler config and starts the inventory downloads.
@event_priority(100)
def on_config(config: MkDocsConfig) -> MkDocsConfig:
    python_handler: dict[str, Any] = config.plugins["mkdocstrings"].config["handlers"].setdefault("python", {})
    python_handler["inventories"] = [
        {"url": inventory_url(name), "base_url": base_url} for name, base_url in INVENTORIES.items()
    ]
    return config


def fetch(name: str) -> bytes | None:
    """Download an upstream inventory, or print why it failed and return None."""
    url = f"{INVENTORIES[name]}objects.inv"
    # URLs come only from the https:// constants above.
    req = urllib.request.Request(url, headers={"User-Agent": "hassette-docs-inventory-refresh"})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:  # noqa: S310
            content = resp.read()
    except (OSError, http.client.HTTPException) as exc:
        print(f"FAILED {name}: {url}: {exc}", file=sys.stderr)
        return None
    if not content.startswith(b"# Sphinx inventory version 2"):
        print(f"FAILED {name}: {url} is not a Sphinx v2 inventory", file=sys.stderr)
        return None
    return content


def refresh() -> int:
    INVENTORY_DIR.mkdir(exist_ok=True)
    failed = 0
    for name in INVENTORIES:
        content = fetch(name)
        if content is None:
            failed += 1
            continue
        inventory_path(name).write_bytes(content)
        print(f"updated {name} ({len(content):,} bytes)")
    return 1 if failed else 0


def check() -> int:
    """Print the names of committed inventories that differ from upstream, space-separated on one line.

    A failed download is a warning, not drift: that inventory is skipped, and the exit code is
    ``INCOMPLETE_CHECK_EXIT_CODE`` so the caller knows an empty list doesn't prove every copy is current.
    """
    drifted: list[str] = []
    failed = 0
    for name in INVENTORIES:
        content = fetch(name)
        if content is None:
            print(f"::warning::Skipped the {name} inventory: download failed", file=sys.stderr)
            failed += 1
            continue
        path = inventory_path(name)
        if not path.is_file() or path.read_bytes() != content:
            drifted.append(name)
    print(" ".join(drifted))
    return INCOMPLETE_CHECK_EXIT_CODE if failed else 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="Refresh the vendored docs inventories, or with --check, report which ones drifted."
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Compare upstream against the committed copies and print the drifted names instead of writing.",
    )
    args = p.parse_args(argv)
    return check() if args.check else refresh()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
