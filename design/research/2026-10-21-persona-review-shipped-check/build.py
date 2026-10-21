"""Build briefings from the shipped doc-persona-review template, under opaque names, plus a manifest.

Run from the repo root after `uv run mkdocs build`:
    uv run --with beautifulsoup4 python design/research/2026-10-21-persona-review-shipped-check/build.py <queue_dir>

Covers the 2026-10-20 control pages (two FastAPI, two Hassette) and E1's seeded copies of one page per site.
Hassette earlier pages come from the built site, as the shipped assembler finds them. FastAPI pages are
local extracts, with their earlier pages listed in FASTAPI_PRIOR.
"""

import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
E1 = HERE.parent / "2026-10-21-persona-review-seeded-recall"
sys.path[:0] = [str(HERE.parents[2] / "tools" / "docs")]
from assemble_persona_briefing import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    PLACEHOLDER_RE,
    TEMPLATE_PATH,
    prior_block,
    prior_pages,
)
from extract_doc_page import extract_page, resolve_html_path  # pyright: ignore[reportMissingImports]  # noqa: E402

RUNS = 2
LINE_RE = re.compile(r"^LINE \d+: ", re.M)
# (page, copy, source file for the page text); None means "extract from the built site".
CELLS = [
    ("fastapi--tutorial--first-steps", "clean", E1 / "variants" / "fastapi--tutorial--first-steps--clean.txt"),
    ("fastapi--tutorial--first-steps", "seeded", E1 / "variants" / "fastapi--tutorial--first-steps--seeded.txt"),
    ("fastapi--tutorial--path-params", "clean", HERE / "pages" / "fastapi--tutorial--path-params.txt"),
    (
        "hassette--getting-started--first-automation",
        "clean",
        E1 / "variants" / "hassette--getting-started--first-automation--clean.txt",
    ),
    (
        "hassette--getting-started--first-automation",
        "seeded",
        E1 / "variants" / "hassette--getting-started--first-automation--seeded.txt",
    ),
    ("hassette--getting-started--index", "clean", None),
]
FASTAPI_PRIOR = {
    "fastapi--tutorial--first-steps": ["fastapi--tutorial--index"],
    "fastapi--tutorial--path-params": ["fastapi--tutorial--index", "fastapi--tutorial--first-steps"],
}
FASTAPI_TEXT = {
    "fastapi--tutorial--index": E1 / "variants" / "fastapi--tutorial--index--clean.txt",
    "fastapi--tutorial--first-steps": E1 / "variants" / "fastapi--tutorial--first-steps--clean.txt",
}
# The shipped reader is written for Hassette; these swap the product so the same reader fits FastAPI.
FASTAPI_SWAPS = [
    (
        "the Hassette documentation, a framework for writing Home Assistant automations\nin Python",
        "the FastAPI documentation, a framework for building web APIs in Python",
    ),
    ("Anything about Hassette", "Anything about FastAPI"),
]


def page_path(slug: str) -> str:
    return "/".join(slug.split("--")[1:])


def numbered(text: str) -> str:
    entries = [e.rstrip("\n") for e in LINE_RE.split(text)[1:] if e.strip()]
    return "\n".join(f"LINE {i}: {e}" for i, e in enumerate(entries, 1))


def plain(text: str) -> str:
    return "\n".join(e.rstrip("\n") for e in LINE_RE.split(text)[1:] if e.strip())


def render(slug: str, source: Path | None) -> str:
    html = resolve_html_path(page_path(slug)) if slug.startswith("hassette") else None
    if slug.startswith("hassette"):
        if html is None:
            raise FileNotFoundError(f"{slug} not in site/; run mkdocs build")
        prior = prior_block(prior_pages(html))
        content = (
            numbered(source.read_text())
            if source
            else "\n".join(f"LINE {i}: {line}" for i, line in enumerate(extract_page(html), 1))
        )
    else:
        if source is None:
            raise ValueError(f"{slug} needs a source file")
        prior = "\n\n".join(
            f"Page: {page_path(p)}\n\n---\n{plain(FASTAPI_TEXT[p].read_text())}\n---" for p in FASTAPI_PRIOR[slug]
        )
        content = numbered(source.read_text())
    values = {"PRIOR_PAGES": prior, "PAGE_PATH": page_path(slug), "PAGE_CONTENT": content}
    template = TEMPLATE_PATH.read_text()
    if slug.startswith("fastapi"):
        for old, new in FASTAPI_SWAPS:
            if old not in template:
                raise ValueError(f"template changed; swap not found: {old!r}")
            template = template.replace(old, new)
    return PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], template)


def main() -> None:
    queue = Path(sys.argv[1])
    queue.mkdir(parents=True, exist_ok=True)
    cells = list(CELLS)
    random.Random(3152).shuffle(cells)  # noqa: S311 — deterministic shuffle for blinding, not crypto
    manifest = {"briefings": {}, "runs": {}}
    for i, (slug, copy, source) in enumerate(cells, 1):
        name = f"b{i:02d}"
        (queue / f"{name}.md").write_text(render(slug, source))
        manifest["briefings"][name] = {"condition": "shipped", "page": slug, "variant": copy}
    runs = [(b, r) for b in manifest["briefings"] for r in range(1, RUNS + 1)]
    random.Random(3153).shuffle(runs)  # noqa: S311 — deterministic shuffle for blinding, not crypto
    for j, (b, r) in enumerate(runs, 1):
        manifest["runs"][f"o{j:02d}"] = {"briefing": b, "run": r}
    (queue / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(len(manifest["briefings"]), "briefings,", len(manifest["runs"]), "runs ->", queue)


if __name__ == "__main__":
    main()
