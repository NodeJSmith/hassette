"""Score a results directory: which seeds and natural defects each run reported, and what else it reported.

Run from this directory: python3 score.py [results|results-opus]

A finding matches a seed or natural defect when its doc_quote contains the seeded wording, so no judge is needed:
agents quote the page's text, and each marker occurs only in the false sentence on its own page.
"""

import collections
import itertools
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
MARKERS = {
    "P1": "and last_changed by default",
    "P2": "Guard(predicate",
    "P3": "raises TypeError",
    "P4": "returns False even if",
    "P5": "ignoring case",
    "P6": "< threshold <=",
    "S1": "| 0 |",
    "S2": "set_error_handler",
    "S3": "empty string raises ValueError",
    "S4": "from wall-clock time, not",
    "S5": "HH:MM:SS",
    "S6": "including CancelledError",
    "L1": "defaults to 30 seconds",
    "L2": "to_thread",
    "L3": "first instantiated",
    "L4": "reported STOPPED",
    "L5": "states.sync",
    "L6": "Before the shutdown hooks run",
    "N1": "glob string",
    "N2": "compiled regex",
}
PAGE_PREFIXES = {"predicate-reference": "PN", "methods": "S", "lifecycle": "L"}
TRACING_SEEDS = {"L4", "L6", "S4"}
SEEDS_PER_PAGE = 6


def match_finding(quote: str, page: str, variant: str) -> list[str]:
    """Return the seed and natural-defect ids this quote matches on this copy of this page."""
    ids = [marker_id for marker_id, marker in MARKERS.items() if marker in quote]
    return [i for i in ids if i[0] in PAGE_PREFIXES[page] and (i[0] == "N" or variant == "seeded")]


def union_recall(runs_by_page: dict[str, list[set[str]]], passes: int) -> float:
    """Mean seed recall when combining every combination of this many runs on each page."""
    rates = []
    for runs in runs_by_page.values():
        rates += [len(set().union(*combo)) / SEEDS_PER_PAGE for combo in itertools.combinations(runs, passes)]
    return round(sum(rates) / len(rates), 3)


def main() -> None:
    results_dir = HERE / (sys.argv[1] if len(sys.argv) > 1 else "results")
    seeds = json.loads((HERE / "seeds.json").read_text())
    manifest = json.loads((HERE / "manifest.json").read_text())
    kinds = {seed["id"]: seed["kind"] for page_seeds in seeds.values() for seed in page_seeds}

    hits = collections.Counter()
    natural = collections.Counter()
    other = collections.defaultdict(list)
    runs_by_page = collections.defaultdict(list)
    tokens = []

    print("page variant run | claims findings tools | matched | other")
    for name, meta in sorted(manifest.items(), key=lambda kv: (kv[1]["slug"], kv[1]["variant"], kv[1]["run"])):
        page = meta["slug"].split("--")[-1]
        variant = meta["variant"]
        result = json.loads((results_dir / f"{name}.json").read_text())
        tokens.append(result["_tokens"])
        found = set()
        extra = 0
        for finding in result["findings"]:
            ids = match_finding(finding["doc_quote"], page, variant)
            found.update(ids)
            if not ids:
                extra += 1
                other[(page, finding["doc_quote"][:70])].append(f"{variant}{meta['run']}")
        for found_id in found:
            (natural if found_id[0] == "N" else hits)[found_id] += 1
        if variant == "seeded":
            runs_by_page[page].append({i for i in found if i[0] != "N"})
        matched = ",".join(sorted(found)) or "-"
        counts = f"{result['claims_checked']} {len(result['findings'])} {result['_tools']}"
        print(f"{page} {variant} {meta['run']} | {counts} | {matched} | {extra}")

    print("\nper-seed (of 3):")
    for seed_id in sorted(kinds, key=lambda s: (kinds[s], s)):
        print(f"  {seed_id} {kinds[seed_id]:20} {hits[seed_id]}/3")

    tracing = sum(hits[i] for i in TRACING_SEEDS)
    direct = sum(hits[i] for i in kinds if i not in TRACING_SEEDS)
    print(f"\noverall {sum(hits.values())}/{len(kinds) * 3}")
    print(f"tracing seeds (grouped after results): {tracing}/{len(TRACING_SEEDS) * 3}")
    print(f"direct lookup: {direct}/{(len(kinds) - len(TRACING_SEEDS)) * 3}")
    print("natural (of 6 runs):", dict(natural))
    print("mean seed recall by passes combined:", {n: union_recall(runs_by_page, n) for n in (1, 2, 3)})
    print(f"mean tokens {round(sum(tokens) / len(tokens))}, total {sum(tokens)}")

    print("\nother findings:")
    for (page, quote), runs in sorted(other.items()):
        print(f"  {page} {runs} :: {quote}")


if __name__ == "__main__":
    main()
