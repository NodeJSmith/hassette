"""Score the runs: write blind judge inputs, then report per-condition results.

Run from the repo root:
    uv run python design/research/2026-10-21-persona-review-seeded-recall/score.py judge-input <queue_dir>
    uv run python design/research/2026-10-21-persona-review-seeded-recall/score.py report <queue_dir>

`judge-input` writes <queue_dir>/judge/<page>.md, one per page, listing every run's findings under its opaque
run id. A judge reads that file and writes <queue_dir>/judge/<page>.json mapping run id -> {seed id: [item
numbers]}. `report` joins those matches with the manifest and prints the table. The judge never sees which
copy (clean or seeded) or condition a run came from.
"""

import collections
import json
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).parent
JUDGE_TASK = """# Matching review findings to known page problems

Below is a list of specific problems that a documentation page may contain, followed by the output of
several independent reviews of that page. Some reviews read a copy of the page that has these problems and
some read a copy that doesn't; you are not told which. Judge each review only on what it says.

For each review, decide which listed problems it identifies. A review identifies a problem when one of its
items points at the same spot on the page and names the same gap: the thing the problem says is missing,
wrong, or contradictory. An item that only mentions the same topic for a different reason does not count
(for example, a complaint that async is hard in general does not identify "the link to the async page was
removed" unless it says the page gives no pointer or explanation for async def). One item can identify at
most one problem.

Write your answer with the Write tool to {out_path} as a JSON object with one key per review id, each
mapping problem ids to the list of item numbers that identify it. Use an empty object for a review that
identifies none. Example: {{"o03": {{"F2": [4]}}, "o11": {{}}}}

## Problems

{problems}

## Reviews

{reviews}
"""


def load_runs(queue: Path) -> tuple[dict, dict]:
    manifest = json.loads((queue / "manifest.json").read_text())
    runs = {}
    for run_id, meta in manifest["runs"].items():
        path = queue / "out" / f"{run_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"missing output {path}")
        runs[run_id] = {**manifest["briefings"][meta["briefing"]], **meta, "result": json.loads(path.read_text())}
    return manifest, runs


def items(result: dict) -> list[str]:
    """Every reviewer statement a judge should consider: findings, failing steps, and unexplained terms."""
    out = [
        f"[{f.get('type')}] L{f.get('line')} {f.get('quote')!r}: {f.get('confusion') or f.get('problem')}"
        for f in result["findings"]
    ]
    out += [
        f"[step cannot be completed] L{s.get('line')} {s.get('step')!r}: {s.get('blocker')}"
        for s in result.get("steps", [])
        if s.get("can_complete") is False
    ]
    out += [
        f"[term not explained] L{t.get('line')} {t.get('term')!r}: {t.get('where')}"
        for t in result.get("terms", [])
        if t.get("explained") is False
    ]
    return out


def judge_input(queue: Path) -> None:
    seeds = json.loads((HERE / "seeds.json").read_text())
    _, runs = load_runs(queue)
    (queue / "judge").mkdir(exist_ok=True)
    for page, page_seeds in seeds.items():
        problems = "\n".join(f"- **{s['id']}** ({s['kind']}): {s['description']}" for s in page_seeds)
        blocks = []
        for run_id in sorted(r for r, m in runs.items() if m["page"] == page):
            lines = "\n".join(f"{i}. {t}" for i, t in enumerate(items(runs[run_id]["result"]), 1)) or "(no items)"
            blocks.append(f"### Review {run_id}\n\n{lines}")
        out_path = queue / "judge" / f"{page}.json"
        text = JUDGE_TASK.format(out_path=out_path, problems=problems, reviews="\n\n".join(blocks))
        (queue / "judge" / f"{page}.md").write_text(text)
        print(queue / "judge" / f"{page}.md")


def verdict(result: dict) -> str:
    if "steps" in result:
        failed = sum(1 for s in result["steps"] if s.get("can_complete") is False)
        return f"{failed}/{len(result['steps'])} steps fail"
    return result.get("overall_verdict", "?")


def report(queue: Path) -> None:
    seeds = json.loads((HERE / "seeds.json").read_text())
    _, runs = load_runs(queue)
    matches = {}
    for page in seeds:
        matches.update(json.loads((queue / "judge" / f"{page}.json").read_text()))
    cells = collections.defaultdict(list)
    for run_id, m in runs.items():
        hit = sorted(s for s, idx in matches.get(run_id, {}).items() if idx)
        cells[(m["page"], m["condition"], m["variant"])].append(
            (len(m["result"]["findings"]), hit, verdict(m["result"]))
        )
    print("| page | cond | copy | findings per run | seeds matched per run | verdicts |")
    print("|---|---|---|---|---|---|")
    for key in sorted(cells):
        rows = cells[key]
        print(
            f"| {key[0].split('--')[0]} | {key[1]} | {key[2]} | {', '.join(str(n) for n, _, _ in rows)} | "
            f"{' ; '.join(','.join(h) or '-' for _, h, _ in rows)} | {' ; '.join(v for _, _, v in rows)} |"
        )
    print()
    print("| cond | seeded recall | clean false-match | mean findings clean | mean findings seeded |")
    print("|---|---|---|---|---|")
    for cond in sorted({c for _, c, _ in cells}):
        seeded = [r for (_, c, v), rs in cells.items() if c == cond and v == "seeded" for r in rs]
        clean = [r for (_, c, v), rs in cells.items() if c == cond and v == "clean" for r in rs]
        recall = sum(len(h) for _, h, _ in seeded) / (4 * len(seeded))
        false = sum(len(h) for _, h, _ in clean) / (4 * len(clean))
        print(
            f"| {cond} | {recall:.0%} | {false:.0%} | {statistics.mean(n for n, _, _ in clean):.1f} | "
            f"{statistics.mean(n for n, _, _ in seeded):.1f} |"
        )


def collect(queue: Path) -> None:
    """Copy run outputs and judge matches into results/ under descriptive names."""
    _, runs = load_runs(queue)
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    for run_id, m in runs.items():
        name = f"{m['condition']}--{m['page']}--{m['variant']}--r{m['run']}.json"
        (out / name).write_text(json.dumps({"run_id": run_id, **m["result"]}, indent=2) + "\n")
    for judged in (queue / "judge").glob("*.json"):
        (out / f"judge--{judged.name}").write_text(judged.read_text())
    (out / "manifest.json").write_text((queue / "manifest.json").read_text())
    print(len(runs), "runs ->", out)


def merge(queue: Path) -> None:
    """Merge the queues named after <queue> into <queue>, renumbering runs so one judge pass scores them all."""
    sources = [Path(p) for p in sys.argv[3:]]
    merged = {"briefings": {}, "runs": {}}
    pooled = []
    for i, src in enumerate(sources):
        manifest, runs = load_runs(src)
        for m in runs.values():
            key = f"q{i}{m['briefing']}"
            merged["briefings"][key] = manifest["briefings"][m["briefing"]]
            pooled.append((key, m["run"], m["result"]))
    random.Random(3150).shuffle(pooled)  # noqa: S311 — deterministic shuffle for blinding, not crypto
    (queue / "out").mkdir(parents=True, exist_ok=True)
    for j, (key, run, result) in enumerate(pooled, 1):
        merged["runs"][f"o{j:02d}"] = {"briefing": key, "run": run}
        (queue / "out" / f"o{j:02d}.json").write_text(json.dumps(result, indent=2) + "\n")
    (queue / "manifest.json").write_text(json.dumps(merged, indent=2) + "\n")
    print(len(pooled), "runs merged ->", queue)


def main() -> None:
    cmd, queue = sys.argv[1], Path(sys.argv[2])
    {"judge-input": judge_input, "report": report, "collect": collect, "merge": merge}[cmd](queue)


if __name__ == "__main__":
    main()
