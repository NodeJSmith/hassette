#!/usr/bin/env python3
"""CI guard: detect un-annotated MUT patches in core test files.

Scans the seven in-scope test files for reassignment or patch.object/patch()
calls that target a prohibited symbol — a method on a method-under-test (MUT)
that should never be patched from the outside. Any such site that lacks a
``# boundary-exempt:`` annotation fails the check.

Prohibited symbols (union across WebsocketService, StateProxy, LifecycleService):

    WebsocketService: make_connection, connect_ws, dispatch, respond_if_necessary,
                      partial_cleanup, authenticate, mark_ready,
                      _emit_readiness_event, subscribe_events,
                      send_connection_established_event
    StateProxy:       load_cache, subscribe_to_events, mark_not_ready,
                      _emit_readiness_event
    Lifecycle:        start_app, stop_app, reload_app, resolve_only_app,
                      handle_crash, detect_changes, refresh_config

The guard is line/regex-based and does not resolve the receiver's class, but it
does require that direct attribute assignments use one of the known service
fixture variable names as the receiver (``websocket_service``, ``state_proxy``,
or ``lifecycle_service``). This prevents false positives from mock App instances
(e.g. ``app1.mark_ready = Mock()``) that happen to share a method name.

For ``patch.object`` and ``monkeypatch.setattr``, the prohibited symbol appears
as a quoted string literal — the match is already precise regardless of receiver.
When such a call spans multiple lines (the symbol string on a continuation line),
the guard re-checks the joined logical statement so the symbol is still detected.

``task_bucket.spawn`` is DELIBERATELY EXCLUDED — it is a method on a different
object (the task bucket), not on the service/proxy/lifecycle under guard.

The ``# boundary-exempt:`` annotation is the escape hatch for sites that are
genuinely mocking a collaborator of the MUT (not the MUT itself). Three
annotation placements are accepted:

    (a) Same physical line as the flagged symbol.
    (b) Any continuation line of the same logical statement — i.e. when the
        flagged line has unbalanced ``(``, scan forward until parens balance and
        accept a ``# boundary-exempt:`` on any of those lines.
    (c) The comment line immediately preceding the flagged statement (no blank
        line between) — for long ``with patch.object(...)`` statements that
        cannot carry a trailing comment within the 120-char limit.

Canonical annotation form: ``# boundary-exempt: collaborator of <method_name>``

Usage:
    python tools/check_internal_patches.py
"""

import re
import sys
from pathlib import Path

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

# Known service fixture variable names used as assignment receivers.
# Direct attribute assignments are only flagged when the receiver matches one of
# these names. This prevents false positives from mock App instances (e.g.
# ``app1.mark_ready = Mock()``) that share method names with the services under guard.
_SERVICE_RECEIVERS: frozenset[str] = frozenset(
    [
        "websocket_service",
        "state_proxy",
        "lifecycle_service",
    ]
)

_SYM_ALT = "|".join(re.escape(s) for s in sorted(PROHIBITED_SYMBOLS, key=len, reverse=True))
_RECV_ALT = "|".join(re.escape(r) for r in sorted(_SERVICE_RECEIVERS, key=len, reverse=True))

# Matches: <known_receiver>.<sym> = ...   (direct assignment on service fixture)
# Excludes == (the zero-width-lookahead ensures the char after = is not =).
_ASSIGN_PATTERN = re.compile(r"(?:^|[(\[,\s])(?P<recv>" + _RECV_ALT + r")\." + r"(?P<sym>" + _SYM_ALT + r")\s*=(?!=)")

# Matches: patch.object(<anything>, "<sym>" or '<sym>'  (any receiver is fine here)
_PATCH_OBJECT_PATTERN = re.compile(r"\bpatch\.object\s*\([^,)]*,\s*['\"](?P<sym>" + _SYM_ALT + r")['\"]")

# Matches: monkeypatch.setattr(<anything>, "<sym>" or '<sym>'
_MONKEYPATCH_PATTERN = re.compile(r"\bmonkeypatch\.setattr\s*\([^,)]*,\s*['\"](?P<sym>" + _SYM_ALT + r")['\"]")

# Matches: patch("<anything>.<sym>"  or patch('<anything>.<sym>'
_PATCH_STR_PATTERN = re.compile(r"""\bpatch\s*\(\s*['"][^'"]*\.(?P<sym>""" + _SYM_ALT + r""")['"]""")

# A patch-family call opener. When such a call spans multiple lines, the prohibited
# symbol string may sit on a continuation line — see _flagged_symbol's joined-statement scan.
_PATCH_FAMILY_OPENER = re.compile(r"\b(?:patch\.object|monkeypatch\.setattr|patch)\s*\(")

# Matches a quoted string literal (single or double), handling escapes — used to blank out
# string contents before counting parens so a "(" inside a string doesn't skew the depth.
_STRING_LITERAL = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'')

ANNOTATION = "# boundary-exempt:"


def _has_annotation(text: str) -> bool:
    return ANNOTATION in text


def _count_open_parens(line: str) -> int:
    """Return net open-paren count for the line (open - close), ignoring parens inside strings."""
    sanitized = _STRING_LITERAL.sub('""', line)
    return sanitized.count("(") - sanitized.count(")")


def _joined_statement(lines: list[str], start_idx: int) -> str:
    """Return the logical statement starting at start_idx, joined through paren balance.

    Joins the opener line with its continuation lines (until parentheses balance) into a
    single space-separated string, so the single-line patch patterns can match a prohibited
    symbol that sits on a continuation line of a multi-line call.
    """
    depth = _count_open_parens(lines[start_idx])
    parts = [lines[start_idx]]
    idx = start_idx + 1
    while idx < len(lines) and depth > 0:
        parts.append(lines[idx])
        depth += _count_open_parens(lines[idx])
        idx += 1
    return " ".join(part.strip() for part in parts)


def _is_exempt(lines: list[str], flagged_idx: int) -> bool:
    """Return True if the flagged line is covered by a boundary-exempt annotation.

    Three accepted placements:
      (a) Same line as the flagged symbol.
      (b) Any continuation line (unbalanced parens on flagged line and forward).
      (c) The comment-only line immediately preceding the flagged statement
          (no blank line between; the preceding line must start with '#' after
          optional whitespace).
    """
    flagged_line = lines[flagged_idx]

    # (a) Same line
    if _has_annotation(flagged_line):
        return True

    # (c) Immediately-preceding comment line — check before (b) so we don't
    # confuse a preceding comment with a continuation of the prior statement.
    if flagged_idx > 0:
        prev_line = lines[flagged_idx - 1]
        stripped_prev = prev_line.strip()
        if stripped_prev.startswith("#") and _has_annotation(stripped_prev):
            return True

    # (b) Continuation lines — scan forward while parens are unbalanced
    depth = _count_open_parens(flagged_line)
    if depth > 0:
        idx = flagged_idx + 1
        while idx < len(lines) and depth > 0:
            cont_line = lines[idx]
            if _has_annotation(cont_line):
                return True
            depth += _count_open_parens(cont_line)
            idx += 1

    return False


def _flagged_symbol(text: str) -> str | None:
    """Return the prohibited symbol if this text is a flagged site, else None.

    Used on a single physical line and, for multi-line patch-family calls, on the
    joined logical statement so a symbol on a continuation line is still detected.
    """
    # Assignment on a known service receiver
    m = _ASSIGN_PATTERN.search(text)
    if m:
        return m.group("sym")

    # patch.object(<obj>, "<sym>", ...)
    m = _PATCH_OBJECT_PATTERN.search(text)
    if m:
        return m.group("sym")

    # monkeypatch.setattr(<obj>, "<sym>", ...)
    m = _MONKEYPATCH_PATTERN.search(text)
    if m:
        return m.group("sym")

    # patch("module.sym", ...)
    m = _PATCH_STR_PATTERN.search(text)
    if m:
        return m.group("sym")

    return None


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return list of (1-based line number, symbol) for un-exempt flagged sites."""
    violations: list[tuple[int, str]] = []
    if not path.exists():
        print(f"WARNING: in-scope file not found: {path}", file=sys.stderr)
        return violations

    lines = path.read_text().splitlines()
    for idx, line in enumerate(lines):
        sym = _flagged_symbol(line)
        # Multi-line patch-family call: the symbol string may be on a continuation
        # line, so the single-line check misses it. When this line opens such a call
        # and the parens don't close on this line, re-check the joined statement.
        if sym is None and _PATCH_FAMILY_OPENER.search(line) and _count_open_parens(line) > 0:
            sym = _flagged_symbol(_joined_statement(lines, idx))
        if sym is None:
            continue
        if not _is_exempt(lines, idx):
            violations.append((idx + 1, sym))  # 1-based line number

    return violations


def main() -> int:
    all_violations: list[tuple[Path, int, str]] = []

    for path in IN_SCOPE_FILES:
        rel = path.relative_to(REPO_ROOT)
        violations = check_file(path)
        for lineno, sym in violations:
            all_violations.append((rel, lineno, sym))

    if all_violations:
        print(f"ERROR: {len(all_violations)} un-annotated MUT patch(es) found in core test files:")
        print()
        for rel, lineno, sym in all_violations:
            print(f"  {rel}:{lineno} — {sym}")
        print()
        print("Each site must carry a '# boundary-exempt: collaborator of <method>' annotation.")
        print("See tests/TESTING.md — 'Mocking at Boundaries' for annotation placement rules.")
        return 1

    total_files = len(IN_SCOPE_FILES)
    print(f"OK: no un-annotated MUT patches found across {total_files} in-scope test files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
