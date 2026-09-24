# REVIEW.md — hassette/

## Export Completeness
`src/hassette/__init__.py` is the package's declared public API — every name an
app author can import as `from hassette import X`. When a change adds or renames
a type app authors are meant to reference directly (an enum, exception, model, or
config class used in method signatures elsewhere in the public surface), does this
diff also import it into `__init__.py` and add it to `__all__`? Check the symbol
against its actual usage in `src/hassette/bus/`, `src/hassette/scheduler/`, and
`src/hassette/api/` public method signatures, not just whether it's importable
from its own submodule — a type can be fully wired into internal call sites while
still being unreachable except via a private submodule path.
