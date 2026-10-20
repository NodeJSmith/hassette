import re
import sys
from pathlib import Path

R = Path(".claude")
S = Path(sys.argv[1])
tpl = (R / "skills/doc-persona-review/references/briefing-template.md").read_text()
personas = (R / "skills/doc-persona-review/references/personas.md").read_text()
alex = re.search(r"## Persona 1:.*?(?=\n---\n)", personas, re.S).group(0).strip()
voice = (R / "rules/voice-guide.md").read_text()
rules = (R / "rules/doc-rules.md").read_text()
GOALS = {
    "hassette": "Follow the getting-started guide from zero to a working automation.",
    "fastapi": "Follow the FastAPI tutorial from zero to a working API.",
}
NAMES = {"hassette": "Hassette", "fastapi": "FastAPI"}
voice_block = re.search(r"## Voice and Structure Context.*?(?=## Your Task)", tpl, re.S).group(0)
must_flag = re.search(r"IMPORTANT: You must genuinely.*?\n", tpl).group(0)
NEUTRAL_TASK = """## Your Task

Read the documentation page below as {{PERSONA_NAME}} would, start to finish.
Stay inside {{PERSONA_NAME}}'s knowledge boundaries:
if something on the page relies on knowledge they don't have and the page doesn't supply it, that is a real problem.
If the page supplies it, or {{PERSONA_NAME}} could reasonably push through, it is not.

Report only problems that would actually slow {{PERSONA_NAME}} down or stop them. Minor polish is not a finding.
An empty findings list is a normal, acceptable result for a well-written page; do not invent problems to fill the list.

Pick the verdict by these rules:
- "followable": no finding would make {{PERSONA_NAME}} stop, re-read a section, or guess.
- "followable-with-effort": at least one finding forces a re-read or a guess, but they still finish.
- "stuck-at-step-N": they cannot continue at step N without outside help.
- "lost": they would abandon the page.

Return your findings as a JSON object:
"""
for page in sorted((S / "pages").glob("*.txt")):
    prod = page.stem.split("--")[0]
    slug = page.stem
    pagepath = "/".join(slug.split("--")[1:])
    for cond in ("a", "b", "c"):
        t = tpl
        if cond in ("b", "c"):
            t = t.replace(voice_block, "")
        if cond == "c":
            t = t.replace(must_flag, "")
            t = re.sub(r"## Your Task.*?Return your findings as a JSON object:\n", NEUTRAL_TASK, t, flags=re.S)
        p = re.sub(r"\*\*Reading goal:\*\*.*", f"**Reading goal:** {GOALS[prod]}", alex)
        t = (
            t.replace("Hassette documentation", f"{NAMES[prod]} documentation")
            .replace("{{PERSONA_DEFINITION}}", p)
            .replace("{{PERSONA_NAME}}", "Alex")
            .replace("{{VOICE_GUIDE}}", voice)
            .replace("{{DOC_RULES}}", rules)
            .replace("{{PAGE_CONTENT}}", page.read_text())
            .replace("{{PAGE_PATH}}", pagepath)
        )
        if "{{" in t:
            raise ValueError(f"unfilled placeholder in {slug} / {cond}")
        (S / "briefings").mkdir(exist_ok=True)
        (S / "briefings" / f"{cond}--{slug}.md").write_text(t)
        print(cond, slug, len(t))
