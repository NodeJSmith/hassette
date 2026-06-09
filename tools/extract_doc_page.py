#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["beautifulsoup4"]
# ///
"""Extract rendered doc page content for persona review.

Reads the built HTML from site/ and extracts the article content as
numbered lines, preserving code blocks and headings. Output is suitable
for feeding directly to LLM persona subagents.

Requires `uv run mkdocs build` to have been run first.

Usage:
    uv run tools/extract_doc_page.py getting-started/first-automation
    uv run tools/extract_doc_page.py core-concepts/bus/index
    uv run tools/extract_doc_page.py --section getting-started
"""

import argparse
import sys
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = REPO_ROOT / "site" / "pages"


def extract_page(html_path: Path) -> list[str]:
    soup = BeautifulSoup(html_path.read_text(), "html.parser")

    article = soup.find("article", class_="md-content__inner")
    if not article:
        return [f"ERROR: no <article class='md-content__inner'> found in {html_path}"]

    lines: list[str] = []

    for element in article.children:
        if isinstance(element, NavigableString):
            text = element.strip()
            if text:
                lines.append(text)
            continue

        if not isinstance(element, Tag):
            continue

        tag = element.name

        if tag in ("h1", "h2", "h3", "h4"):
            prefix = "#" * int(tag[1])
            lines.append(f"{prefix} {element.get_text(strip=True)}")

        elif tag == "pre":
            code = element.find("code")
            if code:
                lines.append("```")
                lines.append(code.get_text())
                lines.append("```")
            else:
                lines.append("```")
                lines.append(element.get_text())
                lines.append("```")

        elif tag == "ul" or tag == "ol":
            lines.extend(
                f"- {li.get_text(separator=' ', strip=True)}" for li in element.find_all("li", recursive=False)
            )

        elif tag == "details":
            summary = element.find("summary")
            summary_text = summary.get_text(strip=True) if summary else ""
            lines.append(f"[COLLAPSIBLE: {summary_text}]")
            for child in element.children:
                if isinstance(child, Tag) and child.name != "summary":
                    text = child.get_text(separator=" ", strip=True)
                    if text:
                        lines.append(f"  {text}")

        elif tag == "div":
            cls = " ".join(element.get("class", []))
            if "admonition" in cls or "note" in cls or "warning" in cls or "tip" in cls:
                title_el = element.find(class_="admonition-title")
                title = title_el.get_text(strip=True) if title_el else ""
                lines.append(f"[ADMONITION: {title}]")
                for child in element.children:
                    if isinstance(child, Tag) and child != title_el:
                        text = child.get_text(separator=" ", strip=True)
                        if text:
                            lines.append(f"  {text}")
            elif "highlight" in cls or "codehilite" in cls:
                code = element.find("code")
                if code:
                    lines.append("```")
                    lines.append(code.get_text())
                    lines.append("```")
            elif "tabbed-set" in cls:
                for tab_content in element.find_all(class_="tabbed-content"):
                    text = tab_content.get_text(separator=" ", strip=True)
                    if text:
                        lines.append(text)
            else:
                text = element.get_text(separator=" ", strip=True)
                if text:
                    lines.append(text)

        elif tag == "p":
            lines.append(element.get_text(separator=" ", strip=True))

        elif tag == "table":
            rows = element.find_all("tr")
            for row in rows:
                cells = [cell.get_text(strip=True) for cell in row.find_all(["th", "td"])]
                lines.append("| " + " | ".join(cells) + " |")

        elif tag == "blockquote":
            text = element.get_text(separator=" ", strip=True)
            if text:
                lines.append(f"> {text}")

        else:
            text = element.get_text(separator=" ", strip=True)
            if text:
                lines.append(text)

    return [line for line in lines if line.strip()]


def resolve_html_path(page_ref: str) -> Path:
    if page_ref.endswith(".md"):
        page_ref = page_ref[:-3]
    if page_ref.endswith("/"):
        page_ref = page_ref[:-1]

    candidate = SITE_DIR / page_ref / "index.html"
    if candidate.exists():
        return candidate

    candidate = SITE_DIR / f"{page_ref}.html"
    if candidate.exists():
        return candidate

    parent = SITE_DIR / page_ref
    if parent.is_dir():
        index = parent / "index.html"
        if index.exists():
            return index

    return SITE_DIR / page_ref / "index.html"


def list_section_pages(section: str) -> list[str]:
    section_dir = SITE_DIR / section
    if not section_dir.is_dir():
        print(f"ERROR: section not found: {section_dir}", file=sys.stderr)
        sys.exit(1)
    pages = []
    for html_file in sorted(section_dir.rglob("index.html")):
        rel = html_file.parent.relative_to(SITE_DIR)
        pages.append(str(rel))
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("page", nargs="?", help="Page path relative to docs/pages/, without .md")
    parser.add_argument("--section", help="Extract all pages in a section")
    parser.add_argument("--list", action="store_true", help="List available pages instead of extracting")
    parser.add_argument("--numbered", action="store_true", default=True, help="Prefix lines with LINE N: (default)")
    parser.add_argument("--raw", action="store_true", help="Output without line numbers")
    args = parser.parse_args()

    if not SITE_DIR.exists():
        print("ERROR: site/ not found. Run `uv run mkdocs build` first.", file=sys.stderr)
        return 1

    if args.list:
        for html_file in sorted(SITE_DIR.rglob("index.html")):
            rel = html_file.parent.relative_to(SITE_DIR)
            print(rel)
        return 0

    if args.section:
        pages = list_section_pages(args.section)
        for page_ref in pages:
            html_path = resolve_html_path(page_ref)
            if not html_path.exists():
                print(f"# SKIP: {page_ref} (not found)", file=sys.stderr)
                continue
            print(f"\n{'=' * 60}")
            print(f"PAGE: {page_ref}")
            print(f"{'=' * 60}")
            lines = extract_page(html_path)
            for i, line in enumerate(lines, 1):
                if args.raw:
                    print(line)
                else:
                    print(f"LINE {i}: {line}")
        return 0

    if not args.page:
        parser.print_help()
        return 1

    html_path = resolve_html_path(args.page)
    if not html_path.exists():
        print(f"ERROR: page not found: {html_path}", file=sys.stderr)
        print(f"  (looked for: {html_path})", file=sys.stderr)
        print("  Run `uv run mkdocs build` to rebuild, or check the page path.", file=sys.stderr)
        return 1

    lines = extract_page(html_path)
    for i, line in enumerate(lines, 1):
        if args.raw:
            print(line)
        else:
            print(f"LINE {i}: {line}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
