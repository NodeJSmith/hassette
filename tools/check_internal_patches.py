#!/usr/bin/env python3
"""CI guard: detect un-annotated MUT patches in core test files.

Scans the seven in-scope test files for reassignment or ``patch.object`` /
``patch()`` / ``monkeypatch.setattr`` calls that target a prohibited symbol — a
method on a method-under-test (MUT) that should never be patched from the
outside. Any such site that lacks a ``# boundary-exempt:`` annotation fails the
check.

Prohibited symbols (union across WebsocketService, StateProxy, LifecycleService):

    WebsocketService: make_connection, connect_ws, dispatch, respond_if_necessary,
                      partial_cleanup, authenticate, mark_ready,
                      _emit_readiness_event, subscribe_events,
                      send_connection_established_event
    StateProxy:       load_cache, subscribe_to_events, mark_not_ready,
                      _emit_readiness_event
    Lifecycle:        start_app, stop_app, reload_app, resolve_only_app,
                      handle_crash, detect_changes, refresh_config

Detection is AST-based. The parser resolves statement boundaries, string
literals, and ``==`` vs ``=`` for free, so the guard matches structure rather
than text:

    * Direct or annotated assignment — ``ast.Assign`` / ``ast.AnnAssign`` whose
      target is ``<receiver>.<symbol>`` where the receiver is a known fixture name
      (``websocket_service``, ``state_proxy``, ``lifecycle_service``). The
      receiver-name check prevents false positives from mock App instances
      (e.g. ``app1.mark_ready = Mock()``) that share a method name. The guard
      does not resolve the receiver's class — the fixture-name allowlist is the
      heuristic that stands in for type resolution.
    * ``patch.object(target, "<symbol>")`` / ``monkeypatch.setattr(target,
      "<symbol>")`` — the prohibited symbol is the quoted second argument; the
      receiver is irrelevant.
    * ``patch("dotted.path.<symbol>")`` — the prohibited symbol is the last
      segment of the quoted import path.

``task_bucket.spawn`` is DELIBERATELY EXCLUDED — it is a method on a different
object (the task bucket), not on the service/proxy/lifecycle under guard. It is
simply absent from the prohibited set.

Two annotations are recognized as escape hatches for different patterns:

    ``# boundary-exempt: collaborator of <method_name>``
        The stub isolates a collaborator that the MUT calls — the method is on
        the same class but is a separate concern being stubbed for isolation.
        Example: mocking ``authenticate`` when testing ``connect_ws``.

    ``# branch-isolation: <method> forced to <behavior> for <target> coverage``
        The stub forces a sibling method to behave a specific way so the test
        can reach a particular branch in the MUT. The goal is not to avoid
        calling the method — it is to control its outcome.
        Example: mocking ``stop_app`` to raise so ``reload_app``'s error path fires.

Annotations are matched via ``tokenize``-derived comment tokens on the flagged
statement's own physical lines, avoiding false positives from annotation text
inside string literals. Two placements are accepted:

    (a) A comment on any physical line of the flagged statement — the same
        line as the symbol, or any continuation line of a multi-line call.
    (b) The comment-only line immediately preceding the flagged statement (no
        blank line between) — for long ``with patch.object(...)`` statements
        that cannot carry a trailing comment within the 120-char limit.

Usage:
    python tools/check_internal_patches.py
"""

import ast
import sys
from pathlib import Path

from lint_helpers import extract_comments

REPO_ROOT = Path(__file__).resolve().parent.parent

IN_SCOPE_FILES: list[Path] = [
    REPO_ROOT / "tests" / "integration" / "test_websocket_service.py",
    REPO_ROOT / "tests" / "unit" / "core" / "test_ws_connection_state.py",
    REPO_ROOT / "tests" / "unit" / "core" / "test_websocket_readiness_events.py",
    REPO_ROOT / "tests" / "integration" / "test_state_proxy.py",
    REPO_ROOT / "tests" / "unit" / "core" / "test_app_lifecycle_service.py",
    REPO_ROOT / "tests" / "unit" / "core" / "test_app_lifecycle_service_operations.py",
    REPO_ROOT / "tests" / "integration" / "test_apps.py",
]

# Union of all prohibited symbol names across WebsocketService, StateProxy, LifecycleService.
# task_bucket.spawn is intentionally excluded — it is on a different object.
PROHIBITED_SYMBOLS: frozenset[str] = frozenset(
    [
        # WebsocketService
        "make_connection",
        "connect_ws",
        "dispatch",
        "respond_if_necessary",
        "partial_cleanup",
        "authenticate",
        "mark_ready",
        "_emit_readiness_event",
        "subscribe_events",
        "send_connection_established_event",
        # StateProxy
        "load_cache",
        "subscribe_to_events",
        "mark_not_ready",
        # _emit_readiness_event already listed above
        # LifecycleService
        "start_app",
        "stop_app",
        "reload_app",
        "resolve_only_app",
        "handle_crash",
        "detect_changes",
        "refresh_config",
    ]
)

# Known service fixture variable names used as assignment receivers. Direct attribute
# assignments are only flagged when the receiver matches one of these names. This prevents
# false positives from mock App instances (e.g. ``app1.mark_ready = Mock()``) that share
# method names with the services under guard.
SERVICE_RECEIVERS: frozenset[str] = frozenset(
    [
        "websocket_service",
        "state_proxy",
        "lifecycle_service",
    ]
)

ANNOTATIONS = ("# boundary-exempt:", "# branch-isolation:")


def func_chain(func: ast.expr) -> list[str]:
    """Return the trailing dotted name parts of a call target.

    ``patch.object`` -> ``["patch", "object"]``; ``mock.patch`` -> ``["mock", "patch"]``;
    ``patch`` -> ``["patch"]``. Subscripts/calls in the chain stop the walk.
    """
    # Walk the attribute chain from leaf to root, then reverse to root-first order.
    parts: list[str] = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return list(reversed(parts))


def string_arg(node: ast.Call, index: int) -> str | None:
    """Return the value of the index-th positional argument if it is a string literal."""
    if index < len(node.args):
        arg = node.args[index]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def string_arg_or_keyword(node: ast.Call, index: int, keyword: str) -> str | None:
    """Return the same argument whether passed positionally (at index) or by keyword.

    ``patch.object``/``monkeypatch.setattr`` accept the patched name positionally or as
    a keyword (``attribute=``/``name=``), so both spellings must resolve to one value.
    """
    sym = string_arg(node, index)
    if sym is not None:
        return sym
    for kw in node.keywords:
        if kw.arg == keyword and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return None


def patch_symbol(node: ast.Call) -> str | None:
    """Return the prohibited symbol targeted by a patch-family call, or None."""
    chain = func_chain(node.func)
    if len(chain) < 1:
        # func is a Call/Subscript (e.g. ``factory()(...)``) — no name to match,
        # and the ``chain[-1]`` access below would otherwise raise IndexError.
        return None

    # patch.object(target, "<sym>") / mock.patch.object(target, attribute="<sym>")
    if chain[-2:] == ["patch", "object"]:
        sym = string_arg_or_keyword(node, 1, "attribute")
        return sym if sym in PROHIBITED_SYMBOLS else None

    # monkeypatch.setattr(target, "<sym>") / monkeypatch.setattr(target, name="<sym>")
    if chain[-2:] == ["monkeypatch", "setattr"]:
        sym = string_arg_or_keyword(node, 1, "name")
        return sym if sym in PROHIBITED_SYMBOLS else None

    # patch("dotted.path.<sym>") / mock.patch("dotted.path.<sym>")
    if chain[-1] == "patch":
        target = string_arg(node, 0)
        if target is not None:
            sym = target.rsplit(".", 1)[-1]
            return sym if sym in PROHIBITED_SYMBOLS else None

    return None


def attribute_targets(target: ast.expr) -> list[ast.Attribute]:
    """Return the attribute nodes among an assignment target (handles tuple/list unpacking)."""
    if isinstance(target, ast.Attribute):
        return [target]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [elt for elt in target.elts if isinstance(elt, ast.Attribute)]
    return []


class PatchVisitor(ast.NodeVisitor):
    """Collect (lineno, end_lineno, symbol) for every flagged site in a module."""

    def __init__(self) -> None:
        self.flagged: list[tuple[int, int, str]] = []

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            for attr in attribute_targets(target):
                if (
                    isinstance(attr.value, ast.Name)
                    and attr.value.id in SERVICE_RECEIVERS
                    and attr.attr in PROHIBITED_SYMBOLS
                ):
                    self.flagged.append((node.lineno, node.end_lineno or node.lineno, attr.attr))
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # Annotated assignment (``state_proxy.load_cache: X = ...``) — single target.
        for attr in attribute_targets(node.target):
            if (
                isinstance(attr.value, ast.Name)
                and attr.value.id in SERVICE_RECEIVERS
                and attr.attr in PROHIBITED_SYMBOLS
            ):
                self.flagged.append((node.lineno, node.end_lineno or node.lineno, attr.attr))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        sym = patch_symbol(node)
        if sym is not None:
            self.flagged.append((node.lineno, node.end_lineno or node.lineno, sym))
        self.generic_visit(node)


def is_exempt(lineno: int, end_lineno: int, comments: dict[int, str]) -> bool:
    """Return True if the statement spanning [lineno, end_lineno] is annotated.

    Checks real comment tokens (via tokenize) on the statement's own physical lines
    and on the comment-only line immediately preceding it (1-based line numbers).
    """
    for line_num in range(lineno, end_lineno + 1):
        comment = comments.get(line_num, "")
        if any(a in comment for a in ANNOTATIONS):
            return True

    prev_comment = comments.get(lineno - 1, "")
    if any(a in prev_comment for a in ANNOTATIONS):
        return True

    return False


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return a sorted list of (1-based line number, symbol) for un-exempt flagged sites."""
    if not path.exists():
        print(f"WARNING: in-scope file not found: {path}", file=sys.stderr)
        return []

    source = path.read_text()
    comments = extract_comments(source)
    visitor = PatchVisitor()
    visitor.visit(ast.parse(source))

    violations = [
        (lineno, sym) for lineno, end_lineno, sym in visitor.flagged if not is_exempt(lineno, end_lineno, comments)
    ]
    return sorted(violations)


def main() -> int:
    all_violations: list[tuple[Path, int, str]] = []

    for path in IN_SCOPE_FILES:
        rel = path.relative_to(REPO_ROOT)
        for lineno, sym in check_file(path):
            all_violations.append((rel, lineno, sym))

    if all_violations:
        print(f"ERROR: {len(all_violations)} un-annotated MUT patch(es) found in core test files:")
        print()
        for rel, lineno, sym in all_violations:
            print(f"  {rel}:{lineno} — {sym}")
        print()
        print("Each site must carry one of:")
        print("  # boundary-exempt: collaborator of <method>  — stubbing a collaborator the MUT calls")
        print("  # branch-isolation: <method> forced to <behavior> for <target> coverage")
        print("See tests/TESTING.md — 'Mocking at Boundaries' for annotation placement rules.")
        return 1

    total_files = len(IN_SCOPE_FILES)
    print(f"OK: no un-annotated MUT patches found across {total_files} in-scope test files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
