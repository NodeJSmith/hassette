#!/usr/bin/env python3
"""CI guard: ban blind **kwargs forwarding typed object/Any into a constructor call.

A ``**kwargs``-shaped parameter typed ``object`` or ``Any`` erases pyright's field-level
checking for everything the caller passes through it. That is usually fine — most
``**kwargs: Any`` parameters forward into another opaque or already-dynamic callable (a
decorator's wrapped function, a cooperative ``super().__init_subclass__(**kwargs)``, a thin
delegate calling its own same-named method) where there was never anything for pyright to
check in the first place. It stops being fine the moment the forwarding target is a locally
meaningful, field-typed constructor: a typo'd field name or a wrong-typed value then only
surfaces at runtime, not from pyright. This happened for real —
``single_point_of_failure_restart(**overrides: object) -> RestartSpec`` forwarded straight
into ``RestartSpec(**overrides)`` behind a ``# pyright: ignore[reportArgumentType]``, and a
throwaway repro confirmed pyright missed a typo'd field name before the fix (see #1780).

Detection is AST-based. For every function/method whose ``**kwargs``-style parameter
(``ast.arguments.kwarg``) is annotated ``object`` or ``Any`` (bare or ``typing.Any``), the
body is scanned for a call that forwards it onward via ``**<same name>``. Only calls whose
target name starts with an uppercase letter are flagged — the PEP 8 convention for a class,
and the shape of the real incident above (``RestartSpec(...)``, not ``some_helper(...)``).
This is a deliberate, narrower net than "any forwarding call": without it, this guard would
also flag every legitimate transparent-proxy pattern already in this codebase (decorator
wrappers forwarding into an ``Any``-typed wrapped callable, ``model_dump`` overrides calling
``super().model_dump(**kwargs)``, sync-facade methods delegating to their async twin,
cooperative ``__init_subclass__``) — none of which lose anything to pyright, since their
forwarding target was never field-typed to begin with. The narrower net does mean a
dynamically-referenced class held in a lowercase variable (``child_class(**kwargs)``) is not
caught — a known, accepted false negative, not a bug in the heuristic.

Fix guidance for a real hit: narrow the outer parameter list to explicit, named parameters
(most callers only need to override a handful of fields), or — if the callee's full field set
genuinely must stay overridable — type the parameter ``**kwargs: Unpack[SomeTypedDict]``
instead of ``object``/``Any`` so pyright can still check it field-by-field.

Escape hatch: a call that is a deliberate, unavoidable passthrough (e.g. a stdlib calling
convention this code doesn't control, like a task factory receiving whatever kwargs a future
Python version's event loop decides to forward) can be annotated on the *call's own line*
with ``# kwargs-forward-ok: <reason>`` to suppress — mirroring the ``# factory-local:``
escape hatch in ``check_test_factories.py``. The reason must be non-empty.

Usage:
    python tools/check_kwargs_forwarding.py [FILE ...]

With no arguments, scans every file under src/hassette. Given file paths (as pre-commit
passes the staged files), scans only those — paths outside src/hassette or non-Python paths
are ignored. Scoped to src/hassette only: this is a framework-API type-safety guard, and
test helpers (which have their own, separate hygiene conventions) are out of scope.
"""

import ast
import re
import sys
from collections.abc import Iterator
from pathlib import Path

from lint_helpers import REPO_ROOT, extract_comments, iter_python_files, run_check

SCAN_DIRS = ["src/hassette"]

ANNOTATION = "# kwargs-forward-ok:"

#: Matches the escape-hatch annotation followed by a non-empty reason.
ANNOTATION_RE = re.compile(r"#\s*kwargs-forward-ok:\s*\S")

FOOTER = (
    "A '**kwargs'/'**overrides' parameter typed 'object'/'Any' that is forwarded via\n"
    "'**<name>' straight into a constructor call erases pyright's field-level checking for\n"
    "every value the caller passes — a typo'd field name or a wrong-typed value only\n"
    "surfaces at runtime. Prefer explicit, named parameters on the outer function, or\n"
    "'**kwargs: Unpack[SomeTypedDict]' if the callee's full field set must stay overridable.\n"
    f"Deliberate, unavoidable passthroughs may be annotated on the call's own line with\n"
    f"'{ANNOTATION} <reason>' to suppress."
)


def _object_or_any(annotation: ast.expr) -> str | None:
    """Return "object"/"Any" if annotation is a bare object/Any type, else None."""
    if isinstance(annotation, ast.Name) and annotation.id in {"object", "Any"}:
        return annotation.id
    if isinstance(annotation, ast.Attribute) and annotation.attr == "Any":
        return "Any"
    return None


def _call_target_name(func_expr: ast.expr) -> str | None:
    """Return the bare name a call targets, for ``Name`` and ``Attribute`` call forms."""
    if isinstance(func_expr, ast.Name):
        return func_expr.id
    if isinstance(func_expr, ast.Attribute):
        return func_expr.attr
    return None


def _looks_like_constructor(name: str) -> bool:
    """True for a PEP 8 class-shaped name (leading uppercase letter)."""
    return name[:1].isupper()


def _is_forwarding_keyword(kw: ast.keyword, kwarg_name: str) -> bool:
    """True for the ``**kwarg_name`` unpacking keyword in a call's argument list.

    ``kw.arg is None`` is what marks a ``**`` unpacking keyword (as opposed to a plain
    ``name=value`` keyword, which always has ``kw.arg`` set).
    """
    return kw.arg is None and isinstance(kw.value, ast.Name) and kw.value.id == kwarg_name


def _binds_name(func: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, name: str) -> bool:
    """True if ``func``'s own parameter list rebinds ``name`` as one of its own parameters."""
    args = func.args
    names = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
    if args.vararg:
        names.append(args.vararg.arg)
    if args.kwarg:
        names.append(args.kwarg.arg)
    return name in names


def _own_scope_nodes(node: ast.AST, kwarg_name: str) -> Iterator[ast.AST]:
    """Yield every descendant of ``node`` that still runs against ``kwarg_name``'s binding.

    Recurses through control flow (``if``/``for``/``with``/``try``/...) and through nested
    functions/lambdas that don't rebind ``kwarg_name`` — those close over the outer binding, so
    a forwarding call inside one is still forwarding the same variable. Stops at a nested
    function/lambda whose own parameter list rebinds ``kwarg_name`` (a different variable that
    merely shares the name) and always stops at class boundaries, which get their own pass via
    ``_iter_functions``.
    """
    for child in ast.iter_child_nodes(node):
        yield child
        if isinstance(child, ast.ClassDef):
            continue
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) and _binds_name(child, kwarg_name):
            continue
        yield from _own_scope_nodes(child, kwarg_name)


def _forwarding_calls(node: ast.FunctionDef | ast.AsyncFunctionDef, kwarg_name: str) -> Iterator[ast.Call]:
    """Yield every call in ``node``'s own scope that forwards ``**kwarg_name`` onward."""
    for inner in _own_scope_nodes(node, kwarg_name):
        if not isinstance(inner, ast.Call):
            continue
        if any(_is_forwarding_keyword(kw, kwarg_name) for kw in inner.keywords):
            yield inner


def _iter_functions(node: ast.AST, qualname: str = "") -> Iterator[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]]:
    """Yield (function node, dotted qualname) for every def reachable from ``node``.

    Descends into classes (prefixing ``Class.``) and into nested functions (prefixing
    ``outer.``), so a decorator's inner ``wrapper`` or a factory's inner closure gets a
    readable qualname in violation messages, not just its bare local name.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield from _iter_functions(child, f"{qualname}{child.name}.")
        elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            full = f"{qualname}{child.name}"
            yield child, full
            yield from _iter_functions(child, f"{full}.")
        else:
            yield from _iter_functions(child, qualname)


def check_source(source: str) -> list[tuple[int, str]]:
    """Return sorted (1-based line number, message) for every blind-kwargs-forward violation."""
    tree = ast.parse(source)
    comments = extract_comments(source)
    violations: list[tuple[int, str]] = []

    for func, qualname in _iter_functions(tree):
        kwarg = func.args.kwarg
        if kwarg is None or kwarg.annotation is None:
            continue
        ann_name = _object_or_any(kwarg.annotation)
        if ann_name is None:
            continue

        for call in _forwarding_calls(func, kwarg.arg):
            target = _call_target_name(call.func)
            if target is None or not _looks_like_constructor(target):
                continue
            if ANNOTATION_RE.search(comments.get(call.lineno, "")):
                continue
            violations.append(
                (
                    call.lineno,
                    f"{qualname}: '**{kwarg.arg}: {ann_name}' forwarded blindly via '**{kwarg.arg}' into {target}(...)",
                )
            )

    return sorted(violations)


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return sorted (1-based line number, message) violations in ``path``."""
    return check_source(path.read_text())


def iter_paths() -> list[Path]:
    """Return every .py file under src/hassette, sorted for stable output."""
    return iter_python_files([], SCAN_DIRS)


def main() -> int:
    return run_check(
        iter_python_files(sys.argv[1:], SCAN_DIRS),
        REPO_ROOT,
        check_file,
        summary="blind **kwargs (typed object/Any) forwarded into a constructor call",
        ok="no blind **kwargs forwarding into a constructor call.",
        footer=FOOTER,
    )


if __name__ == "__main__":
    sys.exit(main())
