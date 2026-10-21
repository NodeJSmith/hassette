"""Build clean and seeded copies of each page from pages/ and seeds.json into variants/.

Run from the repo root: uv run python design/research/2026-10-21-persona-review-seeded-recall/prep.py
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).parent
LINE_RE = re.compile(r"^LINE \d+: ", re.M)
SEP = "\n\x00\n"
# The FastAPI dev-server demo is termynal HTML that the extractor can't flatten; replace it with its plain text.
FASTAPI_DEV_OUTPUT = """$ uv run fastapi dev
 FastAPI   Starting development server 🚀
           Searching for package file structure from directories with __init__.py files
           Importing from /home/user/code/awesomeapp
  module   🐍 main.py
    code   Importing the FastAPI app object from the module with the following code:
           from main import app
     app   Using import string: main:app
  server   Server started at http://127.0.0.1:8000
  server   Documentation at http://127.0.0.1:8000/docs
     tip   Running in development mode, for production use: fastapi run
           Logs:
    INFO   Will watch for changes in these directories: ['/home/user/code/awesomeapp']
    INFO   Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
    INFO   Started reloader process [383138] using WatchFiles
    INFO   Started server process [383153]
    INFO   Waiting for application startup.
    INFO   Application startup complete."""


def read_entries(path: Path) -> list[str]:
    """Split an extracted page into its LINE entries (an entry can span several text lines)."""
    return [e.rstrip("\n") for e in LINE_RE.split(path.read_text())[1:]]


def render(entries: list[str]) -> str:
    kept = [e for e in entries if e.strip()]
    return "".join(f"LINE {i}: {e}\n" for i, e in enumerate(kept, 1))


def clean_entries(slug: str, entries: list[str]) -> list[str]:
    if slug == "fastapi--tutorial--first-steps":
        return [FASTAPI_DEV_OUTPUT if e.startswith("$ <font") else e for e in entries]
    return entries


def apply_seeds(text: str, seeds: list[dict]) -> str:
    """Apply each seed's find/replace once; a newline in `find` also matches an entry boundary.

    `after` (optional) is a unique anchor; the seed's first match after it is the one replaced.
    """
    for seed in seeds:
        start = 0
        if "after" in seed:
            if text.count(seed["after"]) != 1:
                raise ValueError(f"{seed['id']}: anchor must occur exactly once")
            start = text.index(seed["after"]) + len(seed["after"])
        pattern = re.compile(re.escape(seed["find"]).replace("\\\n", f"\n(?:{re.escape(SEP[1:])})?"))
        matches = list(pattern.finditer(text, start))
        if not matches or ("after" not in seed and len(matches) != 1):
            raise ValueError(f"{seed['id']}: find text must match exactly once, matched {len(matches)}")
        m = matches[0]
        text = text[: m.start()] + seed["replace"] + text[m.end() :]
    return text


def main() -> None:
    seeds = json.loads((HERE / "seeds.json").read_text())
    out = HERE / "variants"
    out.mkdir(exist_ok=True)
    for page in sorted((HERE / "pages").glob("*.txt")):
        slug = page.stem
        entries = clean_entries(slug, read_entries(page))
        (out / f"{slug}--clean.txt").write_text(render(entries))
        if slug not in seeds:
            continue
        # Seeds can span entries, so join with a sentinel and split back afterwards.
        seeded = apply_seeds(SEP.join(entries), seeds[slug]).split(SEP)
        (out / f"{slug}--seeded.txt").write_text(render(seeded))
        print(slug, "seeded", len(seeds[slug]))


if __name__ == "__main__":
    main()
