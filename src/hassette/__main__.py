from hassette.config.helpers import get_log_level
from hassette.logging_ import enable_basic_logging


def entrypoint() -> None:
    # Pre-config fallback — Hassette.__init__ re-calls with the full config (including log_format)
    enable_basic_logging(get_log_level(), log_format="auto")

    from hassette.cli import app  # lazy-import: break circular import — cli pulls the full app graph

    app.meta()


if __name__ == "__main__":
    entrypoint()
