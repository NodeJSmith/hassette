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
"""Resource lifecycle hooks that should NOT be wrapped as sync facades.

Counterpart: ``INHERITED_LIFECYCLE_EXCLUSIONS`` in
``tests/unit/test_forgotten_await_completeness.py`` covers the same concept for
the completeness guard (over a wider inherited surface).  A new lifecycle
``async def`` on Resource/Service usually needs an entry in both."""

INTERNAL_METHODS = frozenset(
    {
        "get_job_db_ids",
    }
)
"""Public sync methods that are framework-internal plumbing, not user-facing."""


def safe_parse(source: str, filename: str) -> ast.Module:
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
# When adding such wording to Bus/Scheduler/Api, add a matching pattern here.

# The async sentence opens the body paragraph (preceded by a blank line). Replace with the
# blank line so the one-line summary stays separated from the body.
_ASYNC_SENTENCE_AT_PARAGRAPH_START = re.compile(r"\n\nThis method is\s+``async`` and must be awaited\.\s*")
# The async sentence sits mid-paragraph. Replace with a newline, not a space: the source
# often breaks a line mid-phrase, so collapsing to a space would join two partial lines
# into one that exceeds the 120-char limit and fail ruff validation.
_ASYNC_SENTENCE_MID_PARAGRAPH = re.compile(r"\s*This method is\s+``async`` and must be awaited\.\s*")
# A phrase mutation, not a sentence removal: rewrite the scheduler's "awaited inline" wording.
_AWAITED_INLINE_PHRASE = re.compile(r"is awaited inline")

# T02/T03/T04 added new "Must be awaited" sentences to Bus/Scheduler/Api docstrings.
# Three distinct phrasings require three patterns; order in desync_docstring is load-bearing.

# Api variant: entire standalone paragraph "Must be awaited — a forgotten ``await`` is
# reported per ``forgotten_await_behavior`` (default: warn)." Consume the surrounding blank
# lines so no extra blank line is left behind; the trailing group handles the last-paragraph case.
_MUST_BE_AWAITED_FORGOTTEN_AWAIT = re.compile(
    r"\n\n\s*Must be awaited — a forgotten\s+``await``\s+is reported per\s+"
    r"``forgotten_await_behavior``\s+\(default: warn\)\."
    r"(?:\s*\n\n|\s*$)"
)
# Bus/Scheduler variant: "Must be awaited. Registration/Scheduling completes …" — strip only
# the leading "Must be awaited. " so the informative completion sentence is kept (it remains
# true for sync callers).  The positive lookahead ensures we only strip this prefix when
# followed immediately by an uppercase continuation word.
_MUST_BE_AWAITED_PREFIX = re.compile(r"Must be awaited\.\s+(?=[A-Z])")
# Bus 'on' variant: "...raw topic subscriptions. Must be awaited.\n" — "Must be awaited."
# is appended to the end of an existing sentence rather than starting a new one.  Replace
# ". Must be awaited." with "." to leave the host sentence intact.
_MUST_BE_AWAITED_SENTENCE_SUFFIX = re.compile(r"\. Must be awaited\.")


def desync_docstring(doc: str) -> str:
    """Strip async-specific phrasing from a docstring copied onto a synchronous facade.

    Order matters:
    - ``_ASYNC_SENTENCE_AT_PARAGRAPH_START`` must run before ``_ASYNC_SENTENCE_MID_PARAGRAPH``
      (the latter's leading ``\\s*`` would otherwise consume the blank line the former preserves).
    - ``_MUST_BE_AWAITED_FORGOTTEN_AWAIT`` must run before ``_MUST_BE_AWAITED_PREFIX`` so the
      em-dash variant is consumed in full before the simpler prefix pattern could partially match.
    """
    doc = _ASYNC_SENTENCE_AT_PARAGRAPH_START.sub("\n\n", doc)
    doc = _ASYNC_SENTENCE_MID_PARAGRAPH.sub("\n", doc)
    # Replacement preserves the paragraph break only when one followed the match —
    # a match at end-of-string must not append a spurious trailing blank line.
    doc = _MUST_BE_AWAITED_FORGOTTEN_AWAIT.sub(lambda m: "\n\n" if m.group(0).endswith("\n\n") else "", doc)
    # Suffix before prefix: the suffix pattern matches ". Must be awaited." mid-sentence
    # (same line as the preceding sentence). Strip it first so the prefix pattern's \s+
    # cannot consume the following newline and merge two source lines into one long line.
    doc = _MUST_BE_AWAITED_SENTENCE_SUFFIX.sub(".", doc)
    doc = _MUST_BE_AWAITED_PREFIX.sub("", doc)
    return _AWAITED_INLINE_PHRASE.sub("completes inline", doc)


def unwrap_coroutine_return(node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.expr | None:
    """Return the inner ``T`` expression from a ``Coroutine[Any, Any, T]`` return annotation.

    For ``def foo() -> Coroutine[Any, Any, SomeType]`` (de-asynced form), returns the
    ``SomeType`` node so sync wrappers can emit ``-> SomeType`` rather than the raw
    ``Coroutine[...]`` annotation (which would reference an undefined name in the
    generated file's header). For ``async def`` or any other annotation returns ``None``,
    meaning the caller should use the annotation as-is.

    Also handles quoted (string-literal) annotations: ``-> "Coroutine[Any, Any, T]"`` is
    unwrapped to the string ``"T"`` so the generated file stays valid under
    ``from __future__ import annotations`` environments.
    """
    if isinstance(node, ast.AsyncFunctionDef) or node.returns is None:
        return None
    ret = node.returns
    # Detect quoted annotation and re-parse it
    if isinstance(ret, ast.Constant) and isinstance(ret.value, str):
        try:
            parsed = ast.parse(ret.value, mode="eval")
            inner: ast.expr = parsed.body
        except SyntaxError:
            return None
        quoted = True
    else:
        inner = ret
        quoted = False
    # Must be Coroutine[..., ..., T]
    if not (isinstance(inner, ast.Subscript) and isinstance(inner.value, ast.Name) and inner.value.id == "Coroutine"):
        return None
    # The slice must be a 3-element Tuple: Any, Any, T
    slice_node = inner.slice
    if not (isinstance(slice_node, ast.Tuple) and len(slice_node.elts) == 3):
        return None
    inner_type = slice_node.elts[2]
    if quoted:
        # The original annotation was a quoted string (e.g. -> "Coroutine[Any, Any, Subscription]").
        # Re-parse the inner type string as a real AST expression so the generated sync wrapper
        # emits it as an unquoted runtime annotation (e.g. -> Subscription).  Unquoted annotations
        # keep the import at runtime scope and avoid triggering ruff TC001.
        inner_str = ast.unparse(inner_type)
        try:
            return ast.parse(inner_str, mode="eval").body
        except SyntaxError:
            return inner_type
    return inner_type


def format_return_annotation(func: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Build the ``" -> T"`` suffix for a generated sync method, or ``""`` if unannotated.

    For de-asynced plain-def methods whose return annotation is ``Coroutine[Any, Any, T]``,
    emits ``" -> T"`` (the unwrapped inner type) — the sync wrapper returns the resolved value,
    not the coroutine, and ``Coroutine`` is not imported in the generated file's header.
    Otherwise emits the annotation as written.
    """
    unwrapped = unwrap_coroutine_return(func)
    if unwrapped is not None:
        return f" -> {ast.unparse(unwrapped)}"
    if func.returns:
        return f" -> {ast.unparse(func.returns)}"
    return ""


def has_coroutine_return_annotation(node: ast.FunctionDef) -> bool:
    """Return True if the function's return annotation is a ``Coroutine[...]`` subscript.

    Detects the ``def foo(...) -> Coroutine[Any, Any, T]`` pattern produced by the
    de-asyncing conversion (design/071). The AST shape is ``ast.Subscript`` whose
    ``.value`` is an ``ast.Name`` with ``.id == "Coroutine"``.
    """
    if node.returns is None:
        return False
    ret = node.returns
    # Strip a string annotation — these show up when the return is quoted, e.g.
    # -> "Coroutine[Any, Any, T]".  ast.unparse gives back the inner expression
    # only when we re-parse the constant.
    if isinstance(ret, ast.Constant) and isinstance(ret.value, str):
        try:
            parsed = ast.parse(ret.value, mode="eval")
            ret = parsed.body
        except SyntaxError:
            return False
    return isinstance(ret, ast.Subscript) and isinstance(ret.value, ast.Name) and ret.value.id == "Coroutine"


def is_wrappable(node: ast.stmt) -> TypeGuard[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return True if a class-body node is a public method that should be wrapped.

    Matches both classic ``async def`` methods and plain ``def`` methods whose return
    annotation is a ``Coroutine[...]`` subscript (the de-asynced form introduced in
    design/071). Excludes overloads, Resource lifecycle hooks, and underscore-prefixed
    methods (private registration helpers like ``Bus._on_internal`` must not leak onto
    the facade).
    """
    if isinstance(node, ast.AsyncFunctionDef):
        return not is_overload(node) and node.name not in LIFECYCLE_METHODS and not node.name.startswith("_")
    if isinstance(node, ast.FunctionDef):
        return (
            not is_overload(node)
            and node.name not in LIFECYCLE_METHODS
            and not node.name.startswith("_")
            and has_coroutine_return_annotation(node)
        )
    return False


def is_delegatable(node: ast.stmt) -> TypeGuard[ast.FunctionDef]:
    """Return True if a class-body node is a public sync method that should be delegated.

    Matches plain ``def`` methods that are not properties, lifecycle hooks, overloads,
    private, internal plumbing, or wrappable (a ``def -> Coroutine[...]`` method is
    wrappable, not delegatable — including it in both lists would emit two definitions,
    and the bare passthrough emitted last would silently win).
    """
    if not isinstance(node, ast.FunctionDef):
        return False
    if node.name.startswith("_") or node.name in LIFECYCLE_METHODS or node.name in INTERNAL_METHODS:
        return False
    if is_overload(node):
        return False
    if is_wrappable(node):
        return False
    for deco in node.decorator_list:
        if isinstance(deco, ast.Name) and deco.id == "property":
            return False
    return True
