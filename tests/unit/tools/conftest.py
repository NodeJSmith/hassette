"""Make tools/ importable for unit tests."""

import sys
from pathlib import Path

_TOOLS_DIR = str(Path(__file__).parents[3] / "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
