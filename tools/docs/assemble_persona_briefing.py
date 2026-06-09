#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Assemble a persona briefing file for doc review.

Combines the briefing template with a persona definition, voice guide,
doc rules, and extracted page content into a single file that a subagent
can read and execute.

Usage:
    uv run tools/docs/assemble_persona_briefing.py Alex /tmp/pages/core-concepts--bus--index.txt /tmp/briefings/
    uv run tools/docs/assemble_persona_briefing.py Jordan /tmp/pages/recipes--motion-lights.txt /tmp/briefings/

Output file is named {persona}--{page-slug}.md in the output directory.
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "doc-persona-review"
RULES_DIR = REPO_ROOT / ".claude" / "rules"

TEMPLATE_PATH = SKILL_DIR / "references" / "briefing-template.md"
PERSONAS_PATH = SKILL_DIR / "references" / "personas.md"
VOICE_GUIDE_PATH = RULES_DIR / "voice-guide.md"
DOC_RULES_PATH = RULES_DIR / "doc-rules.md"

PERSONA_PATTERN = re.compile(
    r"^## Persona \d+:.*?\n\*\*Name:\*\* (\w+)\n(.*?)(?=\n---\n|\n## Persona \d+:|\Z)",
    re.MULTILINE | re.DOTALL,
)


def extract_persona(name: str) -> str | None:
    text = PERSONAS_PATH.read_text()
    available = []
    for match in PERSONA_PATTERN.finditer(text):
        available.append(match.group(1))
        if match.group(1).lower() == name.lower():
            return match.group(0).strip()
    print(f"ERROR: persona '{name}' not found. Available: {', '.join(available)}", file=sys.stderr)
    return None


def page_path_from_content_file(content_file: Path) -> str:
    return content_file.stem.replace("--", "/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("persona", help="Persona name (Alex, Sam, or Jordan)")
    parser.add_argument("content_file", help="Path to extracted page content file")
    parser.add_argument("output_dir", help="Directory to write the briefing file")
    args = parser.parse_args()

    content_path = Path(args.content_file)
    if not content_path.exists():
        print(f"ERROR: content file not found: {content_path}", file=sys.stderr)
        return 1

    for path, label in [
        (TEMPLATE_PATH, "briefing template"),
        (PERSONAS_PATH, "personas"),
        (VOICE_GUIDE_PATH, "voice guide"),
        (DOC_RULES_PATH, "doc rules"),
    ]:
        if not path.exists():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    template = TEMPLATE_PATH.read_text()
    persona_def = extract_persona(args.persona)
    if persona_def is None:
        return 1
    voice_guide = VOICE_GUIDE_PATH.read_text()
    doc_rules = DOC_RULES_PATH.read_text()
    page_content = content_path.read_text()
    page_path = page_path_from_content_file(content_path)

    briefing = template.replace("{{PERSONA_NAME}}", args.persona)
    briefing = briefing.replace("{{PERSONA_DEFINITION}}", persona_def)
    briefing = briefing.replace("{{VOICE_GUIDE}}", voice_guide)
    briefing = briefing.replace("{{DOC_RULES}}", doc_rules)
    briefing = briefing.replace("{{PAGE_CONTENT}}", page_content)
    briefing = briefing.replace("{{PAGE_PATH}}", page_path)

    slug = content_path.stem
    out_path = output_dir / f"{args.persona.lower()}--{slug}.md"
    out_path.write_text(briefing)
    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
