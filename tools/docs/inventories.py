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

Refreshing is manual and nothing flags a stale copy. Staleness only costs links to upstream symbols added
since the last refresh, so refresh occasionally rather than on a schedule.
"""

import hashlib
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


def refresh() -> int:
    INVENTORY_DIR.mkdir(exist_ok=True)
    failed = 0
    for name, base_url in INVENTORIES.items():
        url = f"{base_url}objects.inv"
        # URLs come only from the https:// constants above.
        req = urllib.request.Request(url, headers={"User-Agent": "hassette-docs-inventory-refresh"})  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:  # noqa: S310
                content = resp.read()
        except OSError as exc:
            print(f"FAILED {name}: {url}: {exc}", file=sys.stderr)
            failed += 1
            continue
        if not content.startswith(b"# Sphinx inventory version 2"):
            print(f"FAILED {name}: {url} is not a Sphinx v2 inventory", file=sys.stderr)
            failed += 1
            continue
        inventory_path(name).write_bytes(content)
        print(f"updated {name} ({len(content):,} bytes)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(refresh())
