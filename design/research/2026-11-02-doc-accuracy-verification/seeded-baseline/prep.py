"""Build one opaquely named briefing per run from the skill's own template.

Run from the repo root:
    python3 design/research/2026-11-02-doc-accuracy-verification/seeded-baseline/prep.py <out_dir> <runs_per_copy>

Writes <out_dir>/briefings/page-NN.md and <out_dir>/manifest.json. Keep the manifest away from the briefings, and
move this research directory out of the repo while agents run, since it holds the seeds. The template has changed
since this baseline was run, so an exact rerun needs it from the commit that added this directory.
"""

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).parent
TEMPLATE = Path(".claude/skills/doc-accuracy-review/references/briefing-template.md")
SHUFFLE_SEED = 20261102


def apply_seeds(clean: str, page_seeds: list[dict]) -> str:
    """Apply each seed's literal replacement, requiring exactly one match and an unchanged line count."""
    seeded = clean
    for seed in page_seeds:
        if seeded.count(seed["find"]) != 1:
            raise ValueError(f"{seed['id']}: find text must match exactly once")
        seeded = seeded.replace(seed["find"], seed["replace"])
    if clean.count("\n") != seeded.count("\n"):
        raise ValueError("seeds changed the page's line count")
    return seeded


def main() -> None:
    out_dir, runs_per_copy = Path(sys.argv[1]), int(sys.argv[2])
    template = TEMPLATE.read_text()
    seeds = json.loads((HERE / "seeds.json").read_text())

    jobs = []
    for slug, page_seeds in seeds.items():
        clean = (HERE / "pages" / f"{slug}.txt").read_text()
        for variant, text in (("clean", clean), ("seeded", apply_seeds(clean, page_seeds))):
            body = template.replace("{{PAGE_PATH}}", slug.replace("--", "/")).replace("{{PAGE_CONTENT}}", text)
            jobs += [(slug, variant, run, body) for run in range(1, runs_per_copy + 1)]
    random.Random(SHUFFLE_SEED).shuffle(jobs)  # noqa: S311 -- reproducible ordering, not security

    briefings = out_dir / "briefings"
    briefings.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for index, (slug, variant, run, body) in enumerate(jobs, 1):
        name = f"page-{index:02d}"
        (briefings / f"{name}.md").write_text(body)
        manifest[name] = {"slug": slug, "variant": variant, "run": run}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(len(manifest), "briefings")


if __name__ == "__main__":
    main()
