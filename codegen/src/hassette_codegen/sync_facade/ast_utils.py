"""Shared AST utilities for sync facade generation."""

import ast
import builtins
import re
from typing import TypeGuard

# Stub message templates — defined as module-level constants so generated code
# and generator share the same strings. The generated file re-emits these
# verbatim so downstream imports work without sys.path tricks.
STUB_MSG_STATE_CONVERSION = (
    "RecordingApi.sync.{name} is not implemented on the test facade. "
    "Call `harness.api_recorder.sync.get_state(entity_id)` and read the returned state directly."
)
STUB_MSG_GENERIC = (
    "RecordingApi.sync.{name} is not implemented. "
    "Seed state via AppTestHarness.set_state() for read methods, "
    "or use a full integration test for methods requiring a live HA connection."
)
STATE_CONVERSION_METHODS = frozenset({"get_state_value", "get_state_value_typed", "get_attribute"})

# Module-level sets for filtering body-referenced Name nodes during import derivation.
# Use the `builtins` module directly rather than `__builtins__`, which is a dict when
# this file is imported as a module (e.g., under pytest) and returns dict methods instead
# of the actual Python builtins.
BUILTIN_NAMES: frozenset[str] = frozenset(dir(builtins))
WELL_KNOWN_NAMES: frozenset[str] = frozenset(
    {"self", "None", "True", "False", "NotImplementedError", "RuntimeError", "TypeError"}
)

LIFECYCLE_METHODS = frozenset(
    {
        "initialize",
        "shutdown",
        "restart",
        "cleanup",
        "before_initialize",
        "on_initialize",
        "after_initialize",
        "before_shutdown",
        "on_shutdown",
        "after_shutdown",
    }
)
"""Resource lifecycle hooks that should NOT be wrapped as sync facades."""

INTERNAL_METHODS = frozenset(
    {
        "register_and_check_collision",
        "get_job_db_ids",
    }
)
"""Public sync methods that are framework-internal plumbing, not user-facing."""


def _safe_parse(source: str, filename: str) -> ast.Module:
    """Parse Python source, raising SystemExit with a clean message on SyntaxError."""
    try:
        return ast.parse(source, filename=filename)
    except SyntaxError as e:
        raise SystemExit(f"Syntax error in {filename}: {e}") from e


def is_overload(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if this function is an @overload stub."""
    for deco in func.decorator_list:
        if isinstance(deco, ast.Name) and deco.id == "overload":
            return True
        if isinstance(deco, ast.Attribute) and deco.attr == "overload":
            return True
    return False


def format_signature_and_call(func: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, str]:
    """Return (signature_source, call_arguments_source) for a function.

    - Signature includes `self` exactly as in the original.
    - Call string omits `self` and preserves positional, varargs, kwonly, and kwargs.
    """
    args = func.args

    sig_parts: list[str] = []
    call_parts: list[str] = []

    all_positional = args.posonlyargs + args.args
    num_defaults = len(args.defaults)
    first_default = len(all_positional) - num_defaults

    for i, arg in enumerate(all_positional):
        annotation = f": {ast.unparse(arg.annotation)}" if arg.annotation else ""
        default_idx = i - first_default
        if default_idx >= 0:
            default_val = ast.unparse(args.defaults[default_idx])
            sig_parts.append(f"{arg.arg}{annotation} = {default_val}")
        else:
            sig_parts.append(f"{arg.arg}{annotation}")

        if i == 0 and arg.arg == "self":
            continue

        call_parts.append(arg.arg)

        if i == len(args.posonlyargs) - 1 and args.posonlyargs:
            sig_parts.append("/")

    if args.vararg:
        annotation = f": {ast.unparse(args.vararg.annotation)}" if args.vararg.annotation else ""
        sig_parts.append(f"*{args.vararg.arg}{annotation}")
        call_parts.append(f"*{args.vararg.arg}")
    elif args.kwonlyargs:
        sig_parts.append("*")

    kw_defaults = args.kw_defaults
    for i, kwarg in enumerate(args.kwonlyargs):
        annotation = f": {ast.unparse(kwarg.annotation)}" if kwarg.annotation else ""
        default = kw_defaults[i] if i < len(kw_defaults) else None
        if default is not None:
            sig_parts.append(f"{kwarg.arg}{annotation} = {ast.unparse(default)}")
        else:
            sig_parts.append(f"{kwarg.arg}{annotation}")
        call_parts.append(f"{kwarg.arg}={kwarg.arg}")

    if args.kwarg:
        annotation = f": {ast.unparse(args.kwarg.annotation)}" if args.kwarg.annotation else ""
        sig_parts.append(f"**{args.kwarg.arg}{annotation}")
        call_parts.append(f"**{args.kwarg.arg}")

    sig = ", ".join(sig_parts)
    call = ", ".join(call_parts)
    return sig, call


# Async-phrasing patterns stripped from source docstrings when they are copied onto a
# synchronous facade method. The facade is sync, so "this method is async / must be
# awaited" would mislead a user reading the docstring in an IDE. Each pattern's ``\s+``
# tolerates the source wrapping the phrase across lines.
#
# Both `_AT_PARAGRAPH_START` and `_MID_PARAGRAPH` match the same sentence; they differ only
# in surrounding context and replacement, so they are NOT interchangeable and the order in
# `desync_docstring` is load-bearing (see that function).
#
# Coverage caveat: these patterns are coupled to the exact source wording. A *new* async
# phrasing variant (e.g. "must be awaited before returning") would slip through silently —
# the drift gate only detects changes to generated output, not phrasings the regex misses.
# When adding such wording to Bus/Scheduler, add a matching pattern here.

# The async sentence opens the body paragraph (preceded by a blank line). Replace with the
# blank line so the one-line summary stays separated from the body.
_ASYNC_SENTENCE_AT_PARAGRAPH_START = re.compile(r"\n\nThis method is\s+``async`` and must be awaited\.\s*")
# The async sentence sits mid-paragraph. Replace with a newline, not a space: the source
# often breaks a line mid-phrase, so collapsing to a space would join two partial lines
# into one that exceeds the 120-char limit and fail ruff validation.
_ASYNC_SENTENCE_MID_PARAGRAPH = re.compile(r"\s*This method is\s+``async`` and must be awaited\.\s*")
# A phrase mutation, not a sentence removal: rewrite the scheduler's "awaited inline" wording.
_AWAITED_INLINE_PHRASE = re.compile(r"is awaited inline")


def desync_docstring(doc: str) -> str:
    """Strip async-specific phrasing from a docstring copied onto a synchronous facade.

    Order matters: the paragraph-start pattern must run before the mid-paragraph one, since
    the latter's leading ``\\s*`` would otherwise consume the blank line the former preserves.
    """
    doc = _ASYNC_SENTENCE_AT_PARAGRAPH_START.sub("\n\n", doc)
    doc = _ASYNC_SENTENCE_MID_PARAGRAPH.sub("\n", doc)
    return _AWAITED_INLINE_PHRASE.sub("completes inline", doc)


def _is_wrappable(node: ast.stmt) -> TypeGuard[ast.AsyncFunctionDef]:
    """Return True if a class-body node is a public async method that should be wrapped.

    Excludes overloads, Resource lifecycle hooks, and underscore-prefixed methods
    (private registration helpers like ``Bus._on_internal`` must not leak onto the facade).
    """
    return (
        isinstance(node, ast.AsyncFunctionDef)
        and not is_overload(node)
        and node.name not in LIFECYCLE_METHODS
        and not node.name.startswith("_")
    )


def _is_delegatable(node: ast.stmt) -> TypeGuard[ast.FunctionDef]:
    """Return True if a class-body node is a public sync method that should be delegated.

    Matches plain ``def`` methods that are not properties, lifecycle hooks, overloads,
    private, or internal plumbing. These get simple pass-through delegation on the facade.
    """
    if not isinstance(node, ast.FunctionDef):
        return False
    if node.name.startswith("_") or node.name in LIFECYCLE_METHODS or node.name in INTERNAL_METHODS:
        return False
    if is_overload(node):
        return False
    for deco in node.decorator_list:
        if isinstance(deco, ast.Name) and deco.id == "property":
            return False
    return True
