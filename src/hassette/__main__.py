from hassette.config.helpers import get_log_level
from hassette.logging_ import enable_logging


def entrypoint() -> None:
    # Pre-config fallback — Hassette.__init__ re-calls with the full config (including log_format)
    enable_logging(get_log_level(), log_format="auto")

    from hassette.cli import app  # deferred to break circular import at module level

    app.meta()


if __name__ == "__main__":
    entrypoint()
