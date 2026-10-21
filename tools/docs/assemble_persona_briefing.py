#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["beautifulsoup4"]
# ///
"""Assemble a reader briefing for doc-persona-review.

Fills the briefing template with a page and the pages before it in nav order, so the reader treats what those
pages explain as already known. Earlier pages come from the built site's footer "Previous" links, walking back
at most MAX_PRIOR_PAGES and stopping at the edge of the page's top-level section.

Requires `uv run mkdocs build` to have been run first.

Usage:
    uv run tools/docs/assemble_persona_briefing.py getting-started/first-automation /tmp/briefings/

Output file is named {page-slug}.md in the output directory.
"""

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from extract_doc_page import SITE_DIR, extract_page, resolve_html_path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE_PATH = REPO_ROOT / ".claude" / "skills" / "doc-persona-review" / "references" / "briefing-template.md"
SITE_ROOT = SITE_DIR.parent
MAX_PRIOR_PAGES = 3
NO_PRIOR = "(None: this is the first page of its section.)"
PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def previous_page(html_path: Path) -> Path | None:
    """Return the built HTML of the page before ``html_path`` in nav order, or None for the first page."""
    link = BeautifulSoup(html_path.read_text(), "html.parser").select_one("a.md-footer__link--prev")
    href = link.get("href") if link else None
    if not isinstance(href, str):
        return None
    page_url = "/" + html_path.parent.relative_to(SITE_ROOT).as_posix() + "/"
    target = SITE_ROOT / urljoin(page_url, href).strip("/") / "index.html"
    return target if target.exists() else None


def prior_pages(html_path: Path) -> list[Path]:
    """Return up to MAX_PRIOR_PAGES pages before ``html_path`` in its top-level section, earliest first."""
    section = section_of(html_path)
    pages: list[Path] = []
    current = previous_page(html_path)
    while current is not None and len(pages) < MAX_PRIOR_PAGES and section_of(current) == section:
        pages.append(current)
        current = previous_page(current)
    return pages[::-1]


def section_of(html_path: Path) -> tuple[str, ...]:
    return html_path.parent.relative_to(SITE_ROOT).parts[:2]


def prior_block(pages: list[Path]) -> str:
    if not pages:
        return NO_PRIOR
    # Unnumbered, so a reader's LINE N can only refer to the page under review.
    return "\n\n".join(f"Page: {site_path(p)}\n\n---\n" + "\n".join(extract_page(p)) + "\n---" for p in pages)


def numbered(lines: list[str]) -> str:
    return "\n".join(f"LINE {i}: {line}" for i, line in enumerate(lines, 1))


def site_path(html_path: Path) -> str:
    """Return the page path as the skill's arguments spell it, e.g. ``getting-started/first-automation``."""
    path = html_path.parent.relative_to(SITE_ROOT).as_posix()
    return path.removeprefix("pages/") if path != "." else "(home)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("page", help="Page path relative to docs/pages/, without .md")
    parser.add_argument("output_dir", help="Directory to write the briefing file")
    args = parser.parse_args()

    html_path = resolve_html_path(args.page)
    if html_path is None:
        print(f"ERROR: page not found in site/: {args.page!r}. Run `uv run mkdocs build`.", file=sys.stderr)
        return 1

    values = {
        "PRIOR_PAGES": prior_block(prior_pages(html_path)),
        "PAGE_PATH": site_path(html_path),
        "PAGE_CONTENT": numbered(extract_page(html_path)),
    }
    # One pass, so placeholder-like text inside page content is never substituted.
    briefing = PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], TEMPLATE_PATH.read_text())

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{args.page.strip('/').removesuffix('.md').replace('/', '--')}.md"
    out_path.write_text(briefing)
    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
