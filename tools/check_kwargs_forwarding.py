#!/usr/bin/env python3
"""CI guard: ban blind **kwargs forwarding typed object/Any into a constructor call.

A ``**kwargs``-shaped parameter typed ``object`` or ``Any`` erases pyright's field-level
checking for everything the caller passes through it. That is usually fine — most
``**kwargs: Any`` parameters forward into another opaque or already-dynamic callable (a
decorator's wrapped function, a cooperative ``super().__init_subclass__(**kwargs)``, a thin
delegate calling its own same-named method) where there was never anything for pyright to
check in the first place. It stops being fine the moment the forwarding target is a locally
meaningful, field-typed constructor: a typo'd field name or a wrong-typed value then only
surfaces at runtime, not from pyright (see #1780).

Detection is AST-based. For every function/method whose ``**kwargs``-style parameter
(``ast.arguments.kwarg``) is annotated ``object`` or ``Any`` (bare or ``typing.Any``), the
body is scanned for a call that forwards it onward via ``**<same name>``. Only calls whose
target name starts with an uppercase letter are flagged — the PEP 8 convention for a class.
This is a deliberate, narrower net than "any forwarding call": without it, this guard would
also flag every legitimate transparent-proxy pattern already in this codebase (decorator
wrappers forwarding into an ``Any``-typed wrapped callable, ``model_dump`` overrides calling
``super().model_dump(**kwargs)``, sync-facade methods delegating to their async twin,
cooperative ``__init_subclass__``) — none of which lose anything to pyright, since their
forwarding target was never field-typed to begin with. The narrower net accepts known gaps,
not bugs in the heuristic — each requires broader data-flow or scope tracking than this
guard's local, per-call AST check does. Five are false negatives (a real violation goes
unflagged):

- A dynamically-referenced class held in a lowercase variable (``child_class(**kwargs)``).
- Forwarding mediated through an intermediate dict (``defaults.update(overrides);
  Ctor(**defaults)``) rather than a direct ``**kwargs`` unpack.
- A definition-time expression (a default value, decorator, or annotation) in a nested
  function/lambda whose own same-named ``**kwargs`` parameter shadows the outer one — those
  expressions evaluate in the enclosing scope before the inner parameter exists, so they can
  still forward the outer, untyped mapping even though the inner function's body cannot.
- A nested class's method closing over an outer function's ``**kwargs`` (traversal always
  stops at a ``ClassDef`` boundary; see ``_reachable_under_binding``).
- A class-like name that is fully uppercase (an acronym class, e.g. ``URL``, or a single-letter
  name) reached via subscript-unwrapping (``URL[int](**kwargs)``) — indistinguishable by naming
  convention from a callable-map/dispatch-table registry (``HANDLERS[key](**kwargs)``), which
  this guard must not flag (see ``_looks_like_constructor``).

One is a false positive in the opposite direction (a non-violation gets flagged): a
``match``/``case`` binding pattern (``case [kwargs]:``, ``case {"a": kwargs}:``) creates a new
local that shares the outer ``**kwargs`` parameter's name but isn't the same variable —
``_rebinds_name`` only inspects ``Assign``/``AugAssign``/``AnnAssign``/``NamedExpr``/``For``/
``AsyncFor``/``withitem`` targets, not ``ast.match_case`` patterns, so a forwarding call using
that match-bound local is misattributed to the outer, still-untyped parameter.

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

#: Matches the escape-hatch annotation followed by a non-empty reason. Derived from ``ANNOTATION``
#: so the two can't drift apart if the escape-hatch keyword is ever renamed.
ANNOTATION_RE = re.compile(rf"{re.escape(ANNOTATION.lstrip('# ').rstrip(':'))}:\s*\S")

FOOTER = (
    "A '**kwargs'/'**overrides' parameter typed 'object'/'Any' that is forwarded via\n"
    "'**<name>' straight into a constructor call erases pyright's field-level checking for\n"
    "every value the caller passes — a typo'd field name or a wrong-typed value only\n"
    "surfaces at runtime. Prefer explicit, named parameters on the outer function, or\n"
    "'**kwargs: Unpack[SomeTypedDict]' if the callee's full field set must stay overridable.\n"
    "Deliberate, unavoidable passthroughs may be annotated on the call's own line with\n"
    f"'{ANNOTATION} <reason>' to suppress."
)

#: Node types that introduce their own scope for the names assigned inside them: a comprehension's
#: loop variable never leaks into the enclosing function (walrus-in-comprehension's PEP 572
#: exception to this is not modeled — a known, narrow gap).
_OWN_SCOPE_TYPES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


def _object_or_any(annotation: ast.expr) -> str | None:
    """Return "object"/"Any" if annotation is a bare object/Any type, else None."""
    if isinstance(annotation, ast.Name) and annotation.id in {"object", "Any"}:
        return annotation.id
    if isinstance(annotation, ast.Attribute) and annotation.attr == "Any":
        return "Any"
    return None


def _call_target_name(func_expr: ast.expr) -> tuple[str, bool] | None:
    """Return (bare name, was reached via subscript) for ``Name``, ``Attribute``, and subscripted forms.

    A subscripted generic constructor call (``Model[int](**kwargs)``) has a ``Subscript`` func
    expression whose ``.value`` is the actual callee — unwrap it before giving up. The same
    ``Subscript`` shape also covers indexing into a callable-map/dispatch-table registry
    (``HANDLERS[key](**kwargs)``), which is not a constructor call at all — the ``via_subscript``
    flag lets ``_looks_like_constructor`` tell the two apart by naming convention.
    """
    if isinstance(func_expr, ast.Name):
        return func_expr.id, False
    if isinstance(func_expr, ast.Attribute):
        return func_expr.attr, False
    if isinstance(func_expr, ast.Subscript):
        inner = _call_target_name(func_expr.value)
        if inner is None:
            return None
        return inner[0], True
    return None


def _looks_like_constructor(name: str, via_subscript: bool) -> bool:
    """True for a PEP 8 class-shaped name (leading uppercase letter).

    A name reached through subscript-unwrapping that is uppercase throughout (``HANDLERS``,
    ``CLI_FORMATTERS``) is excluded: PEP 8 reserves SCREAMING_SNAKE_CASE for module-level
    constants, and the idiomatic use of an all-caps constant here is a callable-map/dispatch-table
    registry — indexing one and calling the result (``HANDLERS[key](**kwargs)``) is the same
    dynamic-dispatch pattern already excluded for a lowercase-held reference
    (``child_class(**kwargs)``), not a constructor call. A mixed-case name reached the same way
    (``Model`` in ``Model[int](**kwargs)``) still counts — PEP 8 classes are PascalCase, not
    all-caps, so this only narrows the subscripted path.
    """
    if not name[:1].isupper():
        return False
    return not (via_subscript and name.isupper())


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


def _iter_own_scope_body(node: ast.AST) -> Iterator[ast.AST]:
    """Yield every descendant of ``node`` still running in ``node``'s own scope.

    Recurses through control flow (``if``/``for``/``with``/``try``/...) but stops unconditionally
    at any nested scope boundary (see ``_OWN_SCOPE_TYPES``) — used to check whether ``node``
    itself rebinds a name anywhere in its body, not to search for forwarding calls (see
    ``_reachable_under_binding`` for that).
    """
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, _OWN_SCOPE_TYPES):
            yield from _iter_own_scope_body(child)


def _rebinds_name(func: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, name: str) -> bool:
    """True if ``func``'s own scope creates a new local binding for ``name``.

    Its parameter list obviously rebinds. So does a plain assignment target anywhere in its body
    — Python scopes bind at function level, not block level, so ``name = ...`` three ``if``s deep
    still shadows an enclosing function's same-named parameter for the rest of ``func``'s body —
    unless ``func`` declares ``name`` ``nonlocal``/``global``, in which case the assignment
    modifies the outer binding instead of creating a new local one. A lambda body is a single
    expression, so it can only rebind via its own parameters.
    """
    if _binds_name(func, name):
        return True
    if isinstance(func, ast.Lambda):
        return False

    body = list(_iter_own_scope_body(func))
    if any(isinstance(n, ast.Nonlocal | ast.Global) and name in n.names for n in body):
        return False

    for n in body:
        targets: list[ast.expr] = []
        if isinstance(n, ast.Assign):
            targets = n.targets
        elif isinstance(n, ast.AugAssign | ast.AnnAssign | ast.NamedExpr | ast.For | ast.AsyncFor):
            targets = [n.target]
        elif isinstance(n, ast.withitem) and n.optional_vars is not None:
            targets = [n.optional_vars]
        elif isinstance(n, ast.Delete):
            # ``del name`` makes ``name`` local to the enclosing function for its entire body,
            # same as an assignment — CPython's compiler symbol-table analysis treats a bare-name
            # delete target as a binding occurrence, not just a read. ``del kwargs["x"]``/
            # ``del kwargs.attr`` don't count: those targets are Subscript/Attribute, not Name,
            # so they fall through to the Load-context check below like any other mutation.
            targets = n.targets
        for target in targets:
            # A Name leaf in Store or Del context is an actual rebind. A subscript or attribute
            # mutation target (``kwargs["x"] = 1``, ``kwargs.attr = 1``, ``del kwargs["x"]``) walks
            # through a Name in Load context (it's read, then subscripted/attributed into, not
            # rebound) — checking ctx here is what excludes mutation from being mistaken for
            # rebinding.
            if any(
                isinstance(leaf, ast.Name) and leaf.id == name and isinstance(leaf.ctx, ast.Store | ast.Del)
                for leaf in ast.walk(target)
            ):
                return True
    return False


def _reachable_under_binding(node: ast.AST, kwarg_name: str) -> Iterator[ast.AST]:
    """Yield every descendant of ``node`` that still runs against ``kwarg_name``'s binding.

    Recurses through control flow (``if``/``for``/``with``/``try``/...) and through nested
    functions/lambdas that don't rebind ``kwarg_name`` (see ``_rebinds_name``) — those close over
    the outer binding, so a forwarding call inside one is still forwarding the same variable.
    Stops at a nested function/lambda that does rebind ``kwarg_name`` (a different variable that
    merely shares the name) and always stops at class boundaries, which get their own pass via
    ``_iter_functions``.
    """
    for child in ast.iter_child_nodes(node):
        yield child
        if isinstance(child, ast.ClassDef):
            continue
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) and _rebinds_name(child, kwarg_name):
            continue
        yield from _reachable_under_binding(child, kwarg_name)


def _forwarding_calls(node: ast.FunctionDef | ast.AsyncFunctionDef, kwarg_name: str) -> Iterator[ast.Call]:
    """Yield every call in ``node``'s own scope that forwards ``**kwarg_name`` onward."""
    for inner in _reachable_under_binding(node, kwarg_name):
        if not isinstance(inner, ast.Call):
            continue
        if any(_is_forwarding_keyword(kw, kwarg_name) for kw in inner.keywords):
            yield inner


def _iter_functions(node: ast.AST, qualname: str = "") -> Iterator[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]]:
    """Yield (function node, dotted qualname) for every def reachable from ``node``.

    Descends into classes (prefixing ``Class.``) and into nested functions (prefixing
    ``outer.``), so a decorator's inner ``wrapper`` or a factory's inner closure gets a
    readable qualname in violation messages, not just its bare local name. A nested function with
    its own ``**kwargs`` of the same name is checked twice — once as part of the outer function's
    own scan (and skipped there via ``_rebinds_name``), once here as its own top-level entry — an
    accepted, bounded re-walk rather than a bug, since ``check_source`` runs once per file, not
    per line of source.
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
            resolved = _call_target_name(call.func)
            if resolved is None:
                continue
            target, via_subscript = resolved
            if not _looks_like_constructor(target, via_subscript):
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
