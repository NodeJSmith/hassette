"""A text-only docs browser over a built mkdocs site, logging every call to a trace file.

    uv run --with beautifulsoup4 python docsnav.py --site <site_dir> --trace <trace.jsonl> nav
    uv run --with beautifulsoup4 python docsnav.py --site <site_dir> --trace <trace.jsonl> search "<query>"
    uv run --with beautifulsoup4 python docsnav.py --site <site_dir> --trace <trace.jsonl> open <page_path>

`nav` prints the sidebar, `search` ranks sections of search/search_index.json with BM25 (title boosted, as the
site's own search does), and `open` prints a page's text with links resolved to site paths.
"""

import argparse
import collections
import html
import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

# brief.py copies this file out of the repo, so also look for the extractor under the working directory.
sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "tools" / "docs"), str(Path.cwd() / "tools" / "docs")]
from extract_doc_page import extract_page  # pyright: ignore[reportMissingImports]  # noqa: E402

TOKEN_RE = re.compile(r"[\s\-]+")
TAG_RE = re.compile(r"<[^>]+>")
LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "with",
        "my",
        "do",
    ]
)
TITLE_BOOST = 10.0
TOP_N = 8
K1, B = 1.2, 0.75


def tokens(text: str) -> list[str]:
    words = (w.strip(".,:;()[]{}\"'`!?").lower() for w in TOKEN_RE.split(html.unescape(TAG_RE.sub(" ", text))))
    return [w for w in words if w and w not in STOPWORDS]


def search(site: Path, query: str) -> list[dict]:
    docs = json.loads((site / "search" / "search_index.json").read_text())["docs"]
    bags = [collections.Counter(tokens(d["text"])) + _boost(tokens(d["title"])) for d in docs]
    avg = sum(sum(b.values()) for b in bags) / len(bags)
    df = collections.Counter(t for b in bags for t in b)
    scored = []
    for d, bag in zip(docs, bags, strict=True):
        length = sum(bag.values())
        score = 0.0
        for t in set(tokens(query)):
            if t not in bag:
                continue
            idf = math.log(1 + (len(docs) - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * bag[t] * (K1 + 1) / (bag[t] + K1 * (1 - B + B * length / avg))
        if score > 0:
            scored.append((score, d))
    scored.sort(key=lambda x: -x[0])
    return [
        {"location": d["location"], "title": d["title"], "snippet": " ".join(tokens_raw(d["text"]))[:200]}
        for _, d in scored[:TOP_N]
    ]


def _boost(title_tokens: list[str]) -> collections.Counter:
    return collections.Counter({t: TITLE_BOOST * n for t, n in collections.Counter(title_tokens).items()})


def tokens_raw(text: str) -> list[str]:
    return html.unescape(TAG_RE.sub(" ", text)).split()


def open_page(site: Path, page: str) -> str:
    path = page.split("#")[0].strip("/")
    html_path = site / path / "index.html" if path else site / "index.html"
    if not html_path.exists():
        return f"No page at {page!r}. Use a path from nav or search, like pages/core-concepts/bus/."
    base = f"/{path}/" if path else "/"
    lines = [LINK_RE.sub(lambda m: f"]({_resolve(base, m.group(1))})", line) for line in extract_page(html_path)]
    return f"Page: {path or '(home)'}\n" + "\n".join(lines)


def _resolve(base: str, href: str) -> str:
    if href.startswith(("http://", "https://", "mailto:")):
        return href
    return urljoin(base, href).lstrip("/") or "(home)"


def nav(site: Path) -> str:
    soup = BeautifulSoup((site / "index.html").read_text(), "html.parser")
    root = soup.select_one("nav.md-nav--primary")
    if root is None or root.find("ul") is None:
        return "(no navigation found)"
    out: list[str] = []
    _walk(root.find("ul"), 0, out)  # pyright: ignore[reportArgumentType]
    return "\n".join(out)


def _walk(ul: Tag, depth: int, out: list[str]) -> None:
    for li in ul.find_all("li", recursive=False):
        a = li.find("a")
        label = li.find(["a", "label"], recursive=False) or a
        title = " ".join(label.get_text().split()) if label else "?"
        href = a.get("href") if isinstance(a, Tag) and a.find_parent("li") is li else None
        if isinstance(href, str) and href.startswith("#"):
            continue
        out.append("  " * depth + title + (f"  ->  {href}" if href else ""))
        sub = li.find("ul")
        if isinstance(sub, Tag):
            _walk(sub, depth + 1, out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("command", choices=["nav", "search", "open"])
    parser.add_argument("arg", nargs="?", default="")
    args = parser.parse_args()
    if args.command == "search":
        results = search(args.site, args.arg)
        print("\n".join(f"{r['location']}  |  {r['title']}  |  {r['snippet']}" for r in results) or "No results.")
        record = {"cmd": "search", "arg": args.arg, "results": [r["location"] for r in results]}
    elif args.command == "open":
        text = open_page(args.site, args.arg)
        print(text)
        record = {"cmd": "open", "arg": args.arg, "found": not text.startswith("No page at")}
    else:
        print(nav(args.site))
        record = {"cmd": "nav", "arg": ""}
    with args.trace.open("a") as fh:
        fh.write(json.dumps(record) + "\n")


if __name__ == "__main__":
    main()
