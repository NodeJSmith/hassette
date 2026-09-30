"""Shared position-based skip checks for docs pages: code fences, headings, table rows.

Used by check_xref_coverage.py and check_bare_symbols.py so both scripts treat the same
regions of a page as off-limits for symbol matching.
"""

import re


def is_in_code_block(text: str, pos: int) -> bool:
    """Check if position is inside a fenced code block."""
    before = text[:pos]
    fence_count = len(re.findall(r"^```", before, re.MULTILINE))
    return fence_count % 2 == 1


def is_in_heading(text: str, pos: int) -> bool:
    """Check if position is on a heading line."""
    line_start = text.rfind("\n", 0, pos) + 1
    line = text[line_start:pos]
    return line.lstrip().startswith("#")


def is_in_table_row(text: str, pos: int) -> bool:
    """Check if position is in a markdown table row (starts with |)."""
    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    return line.strip().startswith("|") and line.strip().endswith("|")
