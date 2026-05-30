"""Allow ``python -m hassette_codegen.sync_facade`` and ``python codegen/src/hassette_codegen/sync_facade/``."""

import sys
from pathlib import Path

# When run directly (not as part of the installed package), ensure the
# codegen/src directory is on sys.path so package imports work.
_CODEGEN_SRC = str(Path(__file__).resolve().parent.parent.parent)
if _CODEGEN_SRC not in sys.path:
    sys.path.insert(0, _CODEGEN_SRC)

from hassette_codegen.sync_facade.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
