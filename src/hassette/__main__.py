import sys

from hassette.config.helpers import get_log_level
from hassette.logging_ import enable_basic_logging


def entrypoint() -> None:
    # Pre-config fallback — Hassette.__init__ re-calls with the full config (including log_format).
    # stderr, so commands whose stdout is data (`--json`, `hassette run --check`) keep it clean;
    # `hassette run` itself switches to stdout before building its config (cmd_run).
    enable_basic_logging(get_log_level(), log_format="auto", stream=sys.stderr)

    from hassette.cli import app  # house-lint: ignore[HSL002] - break circular import, cli pulls the full app graph

    app.meta()


if __name__ == "__main__":
    entrypoint()
