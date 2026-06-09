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


def emit_code_fence(lines: list[str], text: str, indent: str = "", lang: str = "") -> None:
    lines.append(f"{indent}```{lang}")
    lines.append(text)
    lines.append(f"{indent}```")


def extract_element(element: Tag, lines: list[str], indent: str = "") -> None:
    tag = element.name

    if tag in ("h1", "h2", "h3", "h4"):
        prefix = "#" * int(tag[1])
        lines.append(f"{indent}{prefix} {element.get_text(strip=True)}")

    elif tag == "pre":
        code = element.find("code")
        classes = set(element.get("class", []))
        lang = "mermaid" if "mermaid" in classes else ""
        emit_code_fence(lines, (code or element).get_text(), indent, lang)

    elif tag in ("ul", "ol"):
        lines.extend(
            f"{indent}- {li.get_text(separator=' ', strip=True)}" for li in element.find_all("li", recursive=False)
        )

    elif tag == "details":
        summary = element.find("summary")
        summary_text = summary.get_text(strip=True) if summary else ""
        lines.append(f"{indent}[COLLAPSIBLE: {summary_text}]")
        child_indent = indent + "  "
        for child in element.children:
            if not isinstance(child, Tag) or child.name == "summary":
                continue
            extract_element(child, lines, indent=child_indent)

    elif tag == "div":
        classes = set(element.get("class", []))

        if "admonition" in classes:
            title_el = element.find(class_="admonition-title")
            title = title_el.get_text(strip=True) if title_el else ""
            lines.append(f"{indent}[ADMONITION: {title}]")
            for child in element.children:
                if isinstance(child, Tag) and child != title_el:
                    extract_element(child, lines, indent=indent + "  ")

        elif "highlight" in classes or "codehilite" in classes:
            filename_el = element.find(class_="filename")
            if filename_el:
                lines.append(f"{indent}[FILE: {filename_el.get_text(strip=True)}]")
            code = element.find("code")
            if code:
                emit_code_fence(lines, code.get_text(), indent)

        elif "panzoom-box" in classes:
            pre = element.find("pre", class_="mermaid")
            if pre:
                code = pre.find("code")
                emit_code_fence(lines, (code or pre).get_text(), indent, "mermaid")

        elif "tabbed-set" in classes:
            labels_el = element.find(class_="tabbed-labels")
            labels = [label.get_text(strip=True) for label in labels_el.find_all("label")] if labels_el else []
            blocks = element.find_all(class_="tabbed-block")
            for i, block in enumerate(blocks):
                label = labels[i] if i < len(labels) else f"Tab {i + 1}"
                lines.append(f"{indent}[TAB: {label}]")
                code = block.find("code")
                if code:
                    emit_code_fence(lines, code.get_text(), indent)
                else:
                    text = block.get_text(separator=" ", strip=True)
                    if text:
                        lines.append(f"{indent}  {text}")

        else:
            text = element.get_text(separator=" ", strip=True)
            if text:
                lines.append(f"{indent}{text}")

    elif tag == "p":
        lines.append(f"{indent}{element.get_text(separator=' ', strip=True)}")

    elif tag == "table":
        for row in element.find_all("tr"):
            cells = [cell.get_text(strip=True) for cell in row.find_all(["th", "td"])]
            lines.append(f"{indent}| " + " | ".join(cells) + " |")

    elif tag == "blockquote":
        text = element.get_text(separator=" ", strip=True)
        if text:
            lines.append(f"{indent}> {text}")

    else:
        text = element.get_text(separator=" ", strip=True)
        if text:
            lines.append(f"{indent}{text}")


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
        if isinstance(element, Tag):
            extract_element(element, lines)

    return [line for line in lines if line.strip()]


def print_lines(lines: list[str], *, raw: bool) -> None:
    for i, line in enumerate(lines, 1):
        if raw:
            print(line)
        else:
            print(f"LINE {i}: {line}")


def resolve_html_path(page_ref: str) -> Path | None:
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

    return None


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
    parser.add_argument("--raw", action="store_true", help="Output without LINE N: prefixes")
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
            if html_path is None:
                print(f"# SKIP: {page_ref} (not found)", file=sys.stderr)
                continue
            print(f"\n{'=' * 60}")
            print(f"PAGE: {page_ref}")
            print(f"{'=' * 60}")
            print_lines(extract_page(html_path), raw=args.raw)
        return 0

    if not args.page:
        parser.print_help()
        return 1

    html_path = resolve_html_path(args.page)
    if html_path is None:
        print(f"ERROR: page not found (resolved from: {args.page!r})", file=sys.stderr)
        print("  Run `uv run mkdocs build` to rebuild, or check the page path.", file=sys.stderr)
        return 1

    print_lines(extract_page(html_path), raw=args.raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
