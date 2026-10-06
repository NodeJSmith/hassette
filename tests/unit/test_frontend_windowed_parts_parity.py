import re
from pathlib import Path

from hassette_wire import WINDOWED_ACTIVITY_PARTS

FRONTEND_APP_DATA = Path(__file__).parents[2] / "frontend" / "src" / "utils" / "app-data.ts"
WINDOWED_SET_LITERAL = re.compile(r"const WINDOWED_ACTIVITY_PARTS\b[^=]*=\s*new Set\(\[(?P<items>[^\]]*)\]\)")


def test_frontend_windowed_activity_parts_match_wire() -> None:
    """The frontend's hand-kept ``WINDOWED_ACTIVITY_PARTS`` set names the same parts as the wire's."""
    match = WINDOWED_SET_LITERAL.search(FRONTEND_APP_DATA.read_text())

    assert match, f"no WINDOWED_ACTIVITY_PARTS Set literal found in {FRONTEND_APP_DATA}"
    frontend_parts = set(re.findall(r"[\"']([^\"']+)[\"']", match["items"]))
    assert frontend_parts == WINDOWED_ACTIVITY_PARTS
