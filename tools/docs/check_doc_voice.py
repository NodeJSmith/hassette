#!/usr/bin/env python3
"""CI guard: detect voice and prose anti-patterns in docs/pages/.

Scans docs/pages/ for prose anti-patterns, voice violations, and structural
issues defined in .claude/rules/voice-guide.md and .claude/rules/doc-rules.md.

Rules are context-sensitive: "you/your" is fine in getting-started and recipe
procedure sections but flagged in concept and API reference pages.

Usage:
    python tools/docs/check_doc_voice.py                    # audit all pages
    python tools/docs/check_doc_voice.py --page bus/index   # audit one page
    python tools/docs/check_doc_voice.py --section recipes  # audit one section
    python tools/docs/check_doc_voice.py --rule em-dash      # show only one rule
"""

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCS_DIR = REPO_ROOT / "docs" / "pages"

# Minimum number of Python code lines (excluding fences) to flag as missing snippet
MIN_INLINE_CODE_LINES = 2


# Page classification


COPULA_AVOIDANCE = re.compile(r"\b(serves?\s+as|acts?\s+as|functions?\s+as)\b", re.IGNORECASE)
SIGNIFICANCE_INFLATION = re.compile(
    r"\b(pivotal|crucial|fundamental|robust|essential|paramount|indispensable)\b", re.IGNORECASE
)
DANGLING_ING = re.compile(
    r"(?:^|\.\s+)(Highlighting|Ensuring|Showcasing|Demonstrating|Providing|Fostering|Reflecting)\s",
)
FILLER_HEDGING = re.compile(
    r"\b(it\s+is\s+important\s+to\s+note\s+that|in\s+order\s+to|due\s+to\s+the\s+fact\s+that"
    r"|it\s+should\s+be\s+noted\s+that|it\s+is\s+worth\s+noting\s+that)\b",
    re.IGNORECASE,
)
ABSTRACT_VERBS = re.compile(r"\b(utilize[sd]?|leverag(?:e[sd]?|ing)|facilitate[sd]?)\b", re.IGNORECASE)
SURPRISE_SIGNALS = re.compile(
    r"\b(you\s+might\s+be\s+surprised|surprisingly|contrary\s+to\s+what\s+you\s+might"
    r"|you\s+might\s+expect|unexpectedly)\b",
    re.IGNORECASE,
)
TRANSITION_OPENERS = re.compile(
    r"^(Now\s+that\s+we|Let'?s\s+(?:look|move|turn|explore|dive)"
    r"|Once\s+you(?:'ve|\s+have)|After\s+(?:you(?:'ve|\s+have)|we(?:'ve|\s+have)))",
    re.IGNORECASE,
)
REASSURANCE = re.compile(
    r"\b(don'?t\s+worry|no\s+need\s+to\s+worry|it'?s\s+(?:that\s+)?(?:simple|easy)"
    r"|you'?ll\s+be\s+(?:happy|glad)\s+to\s+know)\b",
    re.IGNORECASE,
)
CHATBOT_PHRASES = re.compile(
    r"\b(I\s+hope\s+this\s+helps|Let\s+me\s+know\s+if|Of\s+course!|Certainly!|Great\s+question"
    r"|You'?re\s+absolutely\s+right|Excellent\s+point)\b",
    re.IGNORECASE,
)
WILL_FUTURE = re.compile(r"\bwill\s+(?:be\s+)?(?:run|fire|execute|call|create|return|send|deliver)\b", re.IGNORECASE)
CAN_BE_USED = re.compile(r"\bcan\s+be\s+used\s+to\b", re.IGNORECASE)
IS_ABLE_TO = re.compile(r"\bis\s+able\s+to\b", re.IGNORECASE)
CATEGORY_DEFINITION = re.compile(
    r"\bis\s+a\s+(?:service|system|mechanism|module|function|class|object|component|utility|tool"
    r"|framework|library|wrapper|helper|interface|abstraction)\b",
    re.IGNORECASE,
)
YOU_YOUR = re.compile(r"\b(you|your|you'?re|you'?ve|you'?ll|you'?d|yourself)\b", re.IGNORECASE)
NEGATIVE_PARALLELISM = re.compile(r"\bit'?s\s+not\s+just\b", re.IGNORECASE)
EM_DASH = re.compile(r"—")


def classify_page(rel_path: str) -> str:
    """Classify a doc page by its path relative to docs/pages/.

    Page types control which voice rules apply:
      - getting-started, migration, procedural: "you/your" allowed
      - recipe: "you" in procedure/variation sections, not in "How It Works"
      - concept: system-as-subject, no "you/your"
    """
    if rel_path.startswith("getting-started/"):
        return "getting-started"
    if rel_path.startswith("recipes/"):
        return "recipe"
    if rel_path.startswith("migration/"):
        return "migration"
    if rel_path.startswith("cli/"):
        return "cli"
    if rel_path.startswith("web-ui/"):
        return "procedural"
    if rel_path.startswith("operating/"):
        return "procedural"
    if rel_path.startswith("testing/"):
        return "procedural"
    if rel_path.startswith("core-concepts/"):
        return "concept"
    if rel_path == "troubleshooting.md":
        return "troubleshooting"
    return "other"


# Section detection within a page


def current_heading(lines: list[str], line_idx: int) -> str:
    """Return the most recent heading text above this line."""
    for i in range(line_idx, -1, -1):
        stripped = lines[i].strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def lines_since_heading(lines: list[str], line_idx: int) -> int:
    """Return how many lines back the nearest heading is, or line_idx if none."""
    for dist in range(1, line_idx + 1):
        if lines[line_idx - dist].strip().startswith("#"):
            return dist
    return line_idx


# Fence tracking (computed once per page)


def compute_code_block_lines(lines: list[str]) -> set[int]:
    """Return the set of line indices that are inside fenced code blocks."""
    inside: set[int] = set()
    in_fence = False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        elif in_fence:
            inside.add(i)
    return inside


# Findings


@dataclass
class Finding:
    file: str
    line: int
    rule: str
    message: str
    snippet: str = ""


@dataclass
class AuditResult:
    findings: list[Finding] = field(default_factory=list)

    def add(self, file: str, line: int, rule: str, message: str, snippet: str = "") -> None:
        self.findings.append(Finding(file=file, line=line, rule=rule, message=message, snippet=snippet))


# Pattern checks


def is_prose_line(line: str) -> bool:
    """Return True if the line is prose (not code, heading, admonition marker, or include).

    List items (- , * ) ARE prose and are checked — only structural markers are skipped.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(("#", "```", "---", "--8<--", "!!!", "???", "|")):
        return False
    if stripped.startswith(("<!--", "{%", "{{", "[//]:")):
        return False
    return True


def is_in_admonition(lines: list[str], line_idx: int) -> bool:
    """Check if a line is indented content inside an admonition block."""
    raw_line = lines[line_idx]
    if not raw_line.startswith("    "):
        return False
    for i in range(line_idx - 1, -1, -1):
        s = lines[i].strip()
        if not s:
            continue
        if s.startswith(("!!!", "???")):
            return True
        if not lines[i].startswith("    "):
            return False
    return False


def check_inline_code_blocks(lines: list[str], rel_path: str, result: AuditResult) -> None:
    """Flag Python code blocks that don't use --8<-- snippet includes."""
    in_fence = False
    fence_start = -1
    fence_is_python = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_fence:
                in_fence = True
                fence_start = i
                fence_is_python = "python" in stripped.lower() or "py" in stripped.lower()
            else:
                if fence_is_python and (i - fence_start) > MIN_INLINE_CODE_LINES:
                    content_lines = lines[fence_start + 1 : i]
                    has_include = any("--8<--" in cl for cl in content_lines)
                    if not has_include:
                        result.add(
                            rel_path,
                            fence_start + 1,
                            "snippet-include",
                            "Python code block without --8<-- snippet include (not CI-tested)",
                            snippet=lines[fence_start].strip(),
                        )
                in_fence = False
                fence_is_python = False


def check_stacked_admonitions(lines: list[str], rel_path: str, result: AuditResult) -> None:
    """Flag consecutive admonition blocks."""
    prev_was_admonition = False
    in_admonition = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("!!!", "???")):
            if prev_was_admonition:
                result.add(
                    rel_path,
                    i + 1,
                    "stacked-admonitions",
                    "Back-to-back admonitions — merge or restructure",
                    snippet=stripped[:80],
                )
            in_admonition = True
        elif in_admonition:
            if not line.startswith("    "):
                in_admonition = False
                prev_was_admonition = True
        else:
            if stripped:
                prev_was_admonition = False


def check_recipe_structure(lines: list[str], rel_path: str, result: AuditResult) -> None:
    """Check recipe pages for required sections."""
    if rel_path.endswith("index.md"):
        return
    headings = [raw.strip().lstrip("#").strip().lower() for raw in lines if raw.strip().startswith("#")]
    required = {
        "the code": "Recipe missing '## The Code' section",
        "how it works": "Recipe missing '## How It Works' section",
    }
    expected = {
        "variations": "Recipe missing '## Variations' section",
        "see also": "Recipe missing '## See Also' section",
    }
    for key, msg in required.items():
        if not any(key in h for h in headings):
            result.add(rel_path, 1, "recipe-structure", msg)
    for key, msg in expected.items():
        if not any(key in h for h in headings):
            result.add(rel_path, 1, "recipe-structure-suggested", msg)


def check_verify_section(lines: list[str], rel_path: str, result: AuditResult) -> None:
    """Check recipe pages for a verification section."""
    if rel_path.endswith("index.md"):
        return
    headings = [raw.strip().lstrip("#").strip().lower() for raw in lines if raw.strip().startswith("#")]
    has_verify = any("verify" in h or "working" in h for h in headings)
    if not has_verify:
        result.add(rel_path, 1, "recipe-verify", "Recipe missing verification section (## Verify It's Working)")


def audit_page(path: Path, result: AuditResult) -> None:
    """Run all checks on a single doc page."""
    rel_path = str(path.relative_to(DOCS_DIR))
    page_type = classify_page(rel_path)
    text = path.read_text()
    lines = text.splitlines()

    is_concept_like = page_type in ("concept", "other")
    checks_reassurance = page_type in ("concept", "recipe", "other")
    code_lines = compute_code_block_lines(lines)

    check_inline_code_blocks(lines, rel_path, result)
    check_stacked_admonitions(lines, rel_path, result)

    if page_type == "recipe":
        check_recipe_structure(lines, rel_path, result)
        check_verify_section(lines, rel_path, result)

    for i, line in enumerate(lines):
        if i in code_lines:
            continue
        if not is_prose_line(line):
            continue

        line_num = i + 1
        stripped = line.strip()
        snip = stripped[:100]

        def flag(rule: str, message: str, _ln: int = line_num, _snip: str = snip) -> None:
            result.add(rel_path, _ln, rule, message, snippet=_snip)

        # Prose anti-patterns (all page types)

        m = COPULA_AVOIDANCE.search(stripped)
        if m:
            flag("copula-avoidance", f'Use "is" or "has" instead of "{m.group()}"')

        m = SIGNIFICANCE_INFLATION.search(stripped)
        if m:
            flag("significance-inflation", f'Inflated word: "{m.group()}"')

        m = DANGLING_ING.search(stripped)
        if m:
            flag("dangling-ing", f'Dangling -ing phrase: "{m.group().strip()}"')

        m = FILLER_HEDGING.search(stripped)
        if m:
            flag("filler-hedging", f'Filler phrase: "{m.group()}" — simplify')

        m = ABSTRACT_VERBS.search(stripped)
        if m:
            flag("abstract-verb", f'"{m.group()}" — use "use", "help", "show"')

        m = SURPRISE_SIGNALS.search(stripped)
        if m and page_type != "troubleshooting":
            flag("surprise-signal", f'No surprise framing: "{m.group()}"')

        m = CHATBOT_PHRASES.search(stripped)
        if m:
            flag("chatbot-phrase", f'Chatbot phrase: "{m.group()}"')

        m = NEGATIVE_PARALLELISM.search(stripped)
        if m:
            flag("negative-parallelism", "State the point directly")

        # Em dashes (per-line)

        if EM_DASH.search(stripped):
            flag("em-dash", "Em dash — use period, comma, or parentheses")

        # Tense and voice (concept/recipe/cli/testing/operating pages)

        if page_type not in ("getting-started", "migration"):
            m = WILL_FUTURE.search(stripped)
            if m:
                flag("future-tense", f'Use present tense: "{m.group()}"')

            m = CAN_BE_USED.search(stripped)
            if m:
                flag("passive-voice", '"can be used to" — rephrase')

            m = IS_ABLE_TO.search(stripped)
            if m:
                flag("passive-voice", '"is able to" — rephrase directly')

        # Category definitions (concept pages, first 3 prose lines of each section)

        if is_concept_like and lines_since_heading(lines, i) <= 3:
            m = CATEGORY_DEFINITION.search(stripped)
            if m:
                flag("category-definition", f'Define by function, not category: "{m.group()}"')

        # "You/your" in concept pages

        if is_concept_like:
            m = YOU_YOUR.search(stripped)
            if m and not is_in_admonition(lines, i):
                flag("you-in-concept", f'"{m.group()}" in concept page — use system-as-subject')

        # "You/your" in recipe "How It Works" (system-as-subject required)

        if page_type == "recipe":
            heading = current_heading(lines, i).lower()
            if "how it works" in heading:
                m = YOU_YOUR.search(stripped)
                if m and not is_in_admonition(lines, i):
                    flag("you-in-how-it-works", f'"{m.group()}" in "How It Works" — use system-as-subject')

        # Transition openers

        if stripped and stripped[0].isupper():
            m = TRANSITION_OPENERS.match(stripped)
            if m:
                flag("transition-opener", f'Transition opener: "{m.group()}" — start directly')

        # Reassurance in concept and recipe pages

        if checks_reassurance:
            m = REASSURANCE.search(stripped)
            if m:
                flag("reassurance", f'Reassurance: "{m.group()}" — assume capable reader')


# Output


def format_findings(result: AuditResult) -> str:
    """Format findings grouped by file."""
    if not result.findings:
        return ""

    by_file: dict[str, list[Finding]] = {}
    for finding in result.findings:
        by_file.setdefault(finding.file, []).append(finding)

    parts: list[str] = []
    for file_path in sorted(by_file):
        parts.append(f"\n{'=' * 70}")
        parts.append(f"  {file_path}")
        parts.append(f"{'=' * 70}")
        for finding in sorted(by_file[file_path], key=lambda x: x.line):
            parts.append(f"  L{finding.line:<5} [{finding.rule}] {finding.message}")
            if finding.snippet:
                parts.append(f"         | {finding.snippet}")
    return "\n".join(parts)


def format_summary(result: AuditResult, page_count: int) -> str:
    """Format a summary of findings by rule."""
    if not result.findings:
        return f"OK: no voice violations found across {page_count} pages."

    by_rule = Counter(finding.rule for finding in result.findings)

    parts = ["\nSummary by rule:"]
    for rule, count in by_rule.most_common():
        parts.append(f"  {count:>4}  {rule}")
    file_count = len({finding.file for finding in result.findings})
    parts.append(f"\n  {len(result.findings)} total findings across {file_count} files ({page_count} pages scanned)")
    return "\n".join(parts)


# Main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--page", help="Audit a single page (path relative to docs/pages/, without .md extension)")
    parser.add_argument("--section", help="Audit one section (e.g., 'recipes', 'core-concepts/bus')")
    parser.add_argument("--rule", help="Show only findings matching this rule name")
    parser.add_argument("--json", action="store_true", help="Output findings as JSON")
    args = parser.parse_args()

    if args.page:
        page_path = DOCS_DIR / (args.page if args.page.endswith(".md") else args.page + ".md")
        if not page_path.exists():
            page_path = DOCS_DIR / args.page / "index.md"
        if not page_path.exists():
            print(f"ERROR: page not found: {args.page}", file=sys.stderr)
            return 1
        pages = [page_path]
    elif args.section:
        section_dir = DOCS_DIR / args.section
        if not section_dir.is_dir():
            print(f"ERROR: section not found: {args.section}", file=sys.stderr)
            return 1
        pages = sorted(section_dir.rglob("*.md"))
    else:
        pages = sorted(DOCS_DIR.rglob("*.md"))

    pages = [p for p in pages if "/snippets/" not in str(p)]

    result = AuditResult()
    for page in pages:
        audit_page(page, result)

    if args.rule:
        result.findings = [f for f in result.findings if f.rule == args.rule]

    if args.json:
        by_rule = Counter(finding.rule for finding in result.findings)
        output = {
            "pages_scanned": len(pages),
            "total_findings": len(result.findings),
            "files_with_findings": len({f.file for f in result.findings}),
            "by_rule": dict(by_rule.most_common()),
            "findings": [asdict(f) for f in result.findings],
        }
        print(json.dumps(output, indent=2))
    else:
        output = format_findings(result)
        if output:
            print(output)
        print(format_summary(result, len(pages)))

    return 1 if result.findings else 0


if __name__ == "__main__":
    sys.exit(main())
