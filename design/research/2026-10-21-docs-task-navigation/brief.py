"""Write one navigation briefing per (task, run) under opaque names, plus a manifest.

Run from the repo root after `uv run mkdocs build`:
    uv run python design/research/2026-10-21-docs-task-navigation/brief.py <tasks.json> <queue_dir> <site_dir> [runs]
"""

import json
import random
import shutil
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "docsnav.py"
REPO = Path(__file__).resolve().parents[3]
BRIEFING = """You're a Python developer who is new to Hassette, a framework for writing Home Assistant automations in
Python. You have a running Home Assistant instance and you've finished Hassette's Quickstart, so you have a small
app running. You don't know Hassette beyond that.

Here is what you want to know:

> {question}

Find the answer in the Hassette documentation. The documentation is only available through this command-line
tool, which works like a browser for the docs site. Use it the way a person uses the site: look at the sidebar,
search, open pages, follow links.

- Show the sidebar:     {cmd} nav
- Search the docs:      {cmd} search "<words>"
- Open a page:          {cmd} open <page path, as shown by nav, search or a link>

Don't read files in the repository or use any other source; the tool is your only window onto the docs. Stop as
soon as you are confident you have the answer, or when you conclude the docs don't cover it.

When you're done, use the Write tool to save a JSON object (only the JSON) to {out}:

{{"answer": "<what to do, concretely: the call, setting, or command and its key arguments>",
  "confidence": "high | medium | low",
  "found_on": ["<page paths where you found it>"],
  "gave_up": false}}

Set "gave_up" to true, and say what you looked for in "answer", if the docs don't answer the question.
Then reply with only the word "done".
"""


def main() -> None:
    tasks = json.loads(Path(sys.argv[1]).read_text())
    queue, site = Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    runs = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    for sub in ("briefings", "out", "traces"):
        (queue / sub).mkdir(parents=True, exist_ok=True)
    tool = queue / "docs.py"
    shutil.copy(TOOL, tool)
    cells = [(t["id"], r) for t in tasks for r in range(1, runs + 1)]
    random.Random(3151).shuffle(cells)  # noqa: S311 — deterministic shuffle for blinding, not crypto
    by_id = {t["id"]: t for t in tasks}
    manifest = {"site": str(site), "runs": {}}
    for i, (task_id, run) in enumerate(cells, 1):
        name = f"n{i:02d}"
        trace = queue / "traces" / f"{name}.jsonl"
        cmd = f"cd {REPO} && uv run --with beautifulsoup4 python {tool} --site {site} --trace {trace}"
        text = BRIEFING.format(question=by_id[task_id]["question"], cmd=cmd, out=queue / "out" / f"{name}.json")
        (queue / "briefings" / f"{name}.md").write_text(text)
        manifest["runs"][name] = {"task": task_id, "run": run}
    (queue / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(len(cells), "briefings ->", queue)


if __name__ == "__main__":
    main()
