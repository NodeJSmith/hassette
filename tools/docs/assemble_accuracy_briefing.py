#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Assemble an accuracy-verification briefing file for doc review.

Combines the accuracy briefing template with extracted page content into a
single file that a verification subagent can read and execute.

Usage:
    uv run tools/docs/assemble_accuracy_briefing.py /tmp/pages/core-concepts--bus--index.txt /tmp/briefings/

Output file is named accuracy--{page-slug}.md in the output directory.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE_PATH = REPO_ROOT / ".claude" / "skills" / "doc-accuracy-review" / "references" / "briefing-template.md"


def page_path_from_content_file(content_file: Path) -> str:
    # extract_doc_page.py encodes page paths as slugs with "--" for "/"
    return content_file.stem.replace("--", "/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("content_file", help="Path to extracted page content file")
    parser.add_argument("output_dir", help="Directory to write the briefing file")
    args = parser.parse_args()

    content_path = Path(args.content_file)
    if not content_path.exists():
        print(f"ERROR: content file not found: {content_path}", file=sys.stderr)
        return 1
    if not TEMPLATE_PATH.exists():
        print(f"ERROR: briefing template not found: {TEMPLATE_PATH}", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    page_path = page_path_from_content_file(content_path)
    briefing = TEMPLATE_PATH.read_text()
    briefing = briefing.replace("{{PAGE_PATH}}", page_path)
    briefing = briefing.replace("{{PAGE_CONTENT}}", content_path.read_text())

    out_path = output_dir / f"accuracy--{content_path.stem}.md"
    out_path.write_text(briefing)
    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
