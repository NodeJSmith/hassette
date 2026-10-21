"""Build one briefing per (condition, page, variant) under opaque names, plus a manifest.

Run from the repo root after prep.py:
    uv run python design/research/2026-10-21-persona-review-seeded-recall/build.py <queue_dir>

Briefings land at <queue_dir>/bNN.md and the manifest at <queue_dir>/manifest.json. Names are opaque so a
reviewer can't tell which copy or condition it was given.
"""

import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
# The skill and doc rules as they were when this experiment ran, before the skill was reworked from its results.
SNAPSHOT = HERE.parent / "2026-10-20-llm-doc-usability-eval" / "control" / "skill-snapshot"

PAGES = ["fastapi--tutorial--first-steps", "hassette--getting-started--first-automation"]
PREVIOUS = {
    "fastapi--tutorial--first-steps": "fastapi--tutorial--index",
    "hassette--getting-started--first-automation": "hassette--getting-started--index",
}
GOALS = {
    "hassette": "Follow the getting-started guide from zero to a working automation.",
    "fastapi": "Follow the FastAPI tutorial from zero to a working API.",
}
NAMES = {"hassette": "Hassette", "fastapi": "FastAPI"}
CONDITIONS = ["a", "c", "s", "p", "t"]
RUNS = 2

NEUTRAL_INTRO = """## Your Task

Read the documentation page below as {{PERSONA_NAME}} would, start to finish.
Stay inside {{PERSONA_NAME}}'s knowledge boundaries:
if something on the page relies on knowledge they don't have and the page doesn't supply it, that is a real problem.
If the page supplies it, or {{PERSONA_NAME}} could reasonably push through, it is not.

Report only problems that would actually slow {{PERSONA_NAME}} down or stop them. Minor polish is not a finding.
An empty findings list is a normal, acceptable result for a well-written page; do not invent problems to fill the list.
"""
VERDICT_RULES = """
Pick the verdict by these rules:
- "followable": no finding would make {{PERSONA_NAME}} stop, re-read a section, or guess.
- "followable-with-effort": at least one finding forces a re-read or a guess, but they still finish.
- "stuck-at-step-N": they cannot continue at step N without outside help.
- "lost": they would abandon the page.
"""
STEP_RULES = """
Then list every step the page asks {{PERSONA_NAME}} to carry out: each instruction to write, save, run, open,
change, or check something. For each step, answer one question: could {{PERSONA_NAME}} complete it correctly
using only this page and what they already know? Answer `true` or `false`. When the answer is
`false`, say in `blocker` what is missing or wrong. A step that works but takes a re-read is `true`.
"""
DEF_RULES = """
Then check the page's vocabulary. List every term, name, concept, or piece of syntax on the page that
{{PERSONA_NAME}} would not already know from their "Knows" list, including everything on their "Does NOT know"
list that the page uses. For each one, answer: does this page{{PRIOR_SCOPE}} explain what it means or what it
does, at or before the point where {{PERSONA_NAME}} needs it? Answer `true` or `false` in `explained`. A link or
pointer that tells them where to learn it counts as `true`. Judge only what the text says, not what you know.
"""
RETURN = "\nReturn your findings as a JSON object:\n"
TERMS_JSON = """  "terms": [
    {"line": 0, "term": "<term>", "explained": true, "where": "<where the page explains it, or what is missing>"}
  ],
"""
STEPS_JSON = """```json
{
  "persona": "{{PERSONA_NAME}}",
  "page": "{{PAGE_PATH}}",
  "steps": [
    {"line": 0, "step": "<the instruction, in a few words>", "can_complete": true, "blocker": null}
  ],
  "findings": [
    {
      "line": 0,
      "section": "<heading text>",
      "type": "undefined-term",
      "quote": "<the specific text that caused confusion>",
      "confusion": "<what {{PERSONA_NAME}} would think or feel at this point>",
      "suggestion": "<what would help>"
    }
  ],
  "summary": "<2-3 sentences: would this persona succeed with this page?>"
}
```"""
PRIOR_PAGE = """## Pages {{PERSONA_NAME}} Has Already Read

{{PERSONA_NAME}} reached this page by following the docs in order and has just finished this page.
Anything it explains, {{PERSONA_NAME}} now knows.

Page: {{PRIOR_PATH}}

---
{{PRIOR_CONTENT}}
---

"""


def find(pattern: str, text: str, flags: int = 0) -> str:
    """Return the first match of pattern in text, failing loudly if it is absent."""
    m = re.search(pattern, text, flags)
    if m is None:
        raise ValueError(f"pattern not found: {pattern}")
    return m.group(0)


def persona(full: str, prod: str, thin: bool) -> str:
    p = re.sub(r"\*\*Reading goal:\*\*.*", f"**Reading goal:** {GOALS[prod]}", full)
    if not thin:
        return p
    keep = [find(r"\*\*Name:\*\*.*", p), find(r"\*\*Knows:\*\*.*?(?=\n\n)", p, re.S)]
    keep += [find(r"\*\*Does NOT know:\*\*.*?(?=\n\n)", p, re.S), find(r"\*\*Reading goal:\*\*.*", p)]
    return "\n\n".join(keep)


def page_path(slug: str) -> str:
    return "/".join(slug.split("--")[1:])


def briefing(cond: str, slug: str, variant: str, tpl: str, alex: str, voice: str, rules: str) -> str:
    """Render one briefing. `cond` is "a" (the current skill) or neutral wording plus any of these letters:
    s = per-step checks instead of a verdict, p = previous page included, d = vocabulary check, t = thin persona.
    """
    prod = slug.split("--")[0]
    t = tpl
    if cond != "a":
        t = t.replace(find(r"## Voice and Structure Context.*?(?=## Your Task)", tpl, re.S), "")
        t = t.replace(find(r"IMPORTANT: You must genuinely.*?\n", tpl), "")
        tail = (STEP_RULES if "s" in cond else VERDICT_RULES) + (DEF_RULES if "d" in cond else "") + RETURN
        t = re.sub(r"## Your Task.*?Return your findings as a JSON object:\n", NEUTRAL_INTRO + tail, t, flags=re.S)
        if "s" in cond:
            t = re.sub(r"```json\n.*?\n```", lambda _: STEPS_JSON, t, count=1, flags=re.S)
        if "d" in cond:
            t = t.replace('  "findings": [', TERMS_JSON + '  "findings": [', 1)
        prior_scope = " or a page they have already read" if "p" in cond else ""
        t = t.replace("{{PRIOR_SCOPE}}", prior_scope)
        if "p" in cond:
            prior = PREVIOUS[slug]
            block = PRIOR_PAGE.replace("{{PRIOR_PATH}}", page_path(prior)).replace(
                "{{PRIOR_CONTENT}}", (HERE / "variants" / f"{prior}--clean.txt").read_text()
            )
            t = t.replace("## Page Content", block + "## Page Content")
    t = (
        t.replace("Hassette documentation", f"{NAMES[prod]} documentation")
        .replace("{{PERSONA_DEFINITION}}", persona(alex, prod, thin="t" in cond))
        .replace("{{PERSONA_NAME}}", "Alex")
        .replace("{{VOICE_GUIDE}}", voice)
        .replace("{{DOC_RULES}}", rules)
        .replace("{{PAGE_CONTENT}}", (HERE / "variants" / f"{slug}--{variant}.txt").read_text())
        .replace("{{PAGE_PATH}}", page_path(slug))
    )
    if "{{" in t:
        raise ValueError(f"unfilled placeholder in {cond} / {slug} / {variant}")
    return t


def main() -> None:
    queue = Path(sys.argv[1])
    conditions = sys.argv[2:] or CONDITIONS
    queue.mkdir(parents=True, exist_ok=True)
    tpl = (SNAPSHOT / "briefing-template.md").read_text()
    alex = find(r"## Persona 1:.*?(?=\n---\n)", (SNAPSHOT / "personas.md").read_text(), re.S).strip()
    voice = (SNAPSHOT / "voice-guide.md").read_text()
    rules = (SNAPSHOT / "doc-rules.md").read_text()
    cells = [(c, s, v) for c in conditions for s in PAGES for v in ("clean", "seeded")]
    random.Random(3148).shuffle(cells)  # noqa: S311 — deterministic shuffle for blinding, not crypto
    manifest = {"briefings": {}, "runs": {}}
    for i, (cond, slug, variant) in enumerate(cells, 1):
        name = f"b{i:02d}"
        (queue / f"{name}.md").write_text(briefing(cond, slug, variant, tpl, alex, voice, rules))
        manifest["briefings"][name] = {"condition": cond, "page": slug, "variant": variant}
    runs = [(b, r) for b in manifest["briefings"] for r in range(1, RUNS + 1)]
    random.Random(3149).shuffle(runs)  # noqa: S311 — deterministic shuffle for blinding, not crypto
    for j, (b, r) in enumerate(runs, 1):
        manifest["runs"][f"o{j:02d}"] = {"briefing": b, "run": r}
    (queue / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(len(manifest["briefings"]), "briefings,", len(manifest["runs"]), "runs ->", queue)


if __name__ == "__main__":
    main()
