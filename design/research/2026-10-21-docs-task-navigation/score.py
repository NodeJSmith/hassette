"""Collect trace metrics and answers for a navigation run, and merge in a judge's verdicts.

Run from this directory's repo root, with D=design/research/2026-10-21-docs-task-navigation:
    uv run python $D/score.py $D/tasks.json <queue_dir> judge-input
    uv run python $D/score.py $D/tasks.json <queue_dir> report [verdicts.json]

`judge-input` writes <queue_dir>/judge.md: each run's question, expected answer and given answer under its opaque
name, with nothing about the trace. `report` prints a markdown table of trace metrics per task, joined to the
verdicts (a JSON object of name -> {"verdict": ..., "note": ...}) when given.
"""

import json
import sys
from pathlib import Path


def load(queue: Path) -> tuple[dict, dict]:
    manifest = json.loads((queue / "manifest.json").read_text())
    runs = {}
    for name, cell in sorted(manifest["runs"].items()):
        out = queue / "out" / f"{name}.json"
        trace = queue / "traces" / f"{name}.jsonl"
        answer = json.loads(out.read_text()) if out.exists() else None
        calls = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
        runs[name] = {**cell, "answer": answer, "calls": calls}
    return manifest, runs


def metrics(calls: list[dict], sources: list[str]) -> dict:
    opens = [c for c in calls if c["cmd"] == "open"]
    opened = [c["arg"].split("#")[0].strip("/") + "/" for c in opens if c["found"]]
    srcs = {s.strip("/") + "/" for s in sources}
    first_src = next((i for i, c in enumerate(calls, 1) if c["cmd"] == "open" and _page(c) in srcs), None)
    return {
        "calls": len(calls),
        "nav": sum(c["cmd"] == "nav" for c in calls),
        "searches": sum(c["cmd"] == "search" for c in calls),
        "opens": len(opens),
        "not_found": sum(not c["found"] for c in opens),
        "source_opened": bool(srcs & set(opened)),
        "calls_to_source": first_src,
        "search_hit_source": any(
            {r.split("#")[0].strip("/") + "/" for r in c["results"]} & srcs for c in calls if c["cmd"] == "search"
        ),
    }


def _page(call: dict) -> str:
    return call["arg"].split("#")[0].strip("/") + "/"


def judge_input(tasks: dict, runs: dict, queue: Path) -> None:
    parts = []
    for name, run in runs.items():
        task = tasks[run["task"]]
        answer = json.dumps(run["answer"], indent=2) if run["answer"] else "(no answer file written)"
        parts.append(
            f"## {name}\n\n**Question:** {task['question']}\n\n**Expected:** {task['expected']}\n\n"
            f"**Given answer:**\n\n```json\n{answer}\n```\n"
        )
    (queue / "judge.md").write_text("\n".join(parts))
    print("wrote", queue / "judge.md")


def report(tasks: dict, runs: dict, verdicts: dict) -> None:
    print(
        "| run | task | verdict | calls | nav | searches | opens | 404s | source opened | calls to source "
        "| search surfaced source | confidence |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name, run in sorted(runs.items(), key=lambda kv: kv[1]["task"]):
        m = metrics(run["calls"], tasks[run["task"]]["sources"])
        conf = run["answer"]["confidence"] if run["answer"] else "-"
        verdict = verdicts.get(name, {}).get("verdict", "?")
        print(
            f"| {name} | {run['task']} | {verdict} | {m['calls']} | {m['nav']} | {m['searches']} | {m['opens']} "
            f"| {m['not_found']} | {'yes' if m['source_opened'] else 'no'} | {m['calls_to_source'] or '-'} "
            f"| {'yes' if m['search_hit_source'] else 'no'} | {conf} |"
        )


def main() -> None:
    tasks = {t["id"]: t for t in json.loads(Path(sys.argv[1]).read_text())}
    queue = Path(sys.argv[2])
    _, runs = load(queue)
    if sys.argv[3] == "judge-input":
        judge_input(tasks, runs, queue)
    else:
        verdicts = json.loads(Path(sys.argv[4]).read_text()) if len(sys.argv) > 4 else {}
        report(tasks, runs, verdicts)


if __name__ == "__main__":
    main()
