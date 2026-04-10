"""Unit tests for tools/generate_sync_facade.py — recording facade extensions."""

import ast
import copy
import py_compile
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

# Add the tools directory to sys.path so we can import the generator
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "tools"))


from generate_sync_facade import (  # noqa: E402
    _build_precise_import_block,
    _collect_module_level_import_map,
    _collect_referenced_symbols,
    _derive_recording_imports_strict,
    _format_via_ruff,
    _RecordingBodyRewriter,
    gen_recording_method,
    generate_sync_recording,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RECORDING_API_PATH = _REPO_ROOT / "src" / "hassette" / "test_utils" / "recording_api.py"
_API_PATH = _REPO_ROOT / "src" / "hassette" / "api" / "api.py"


def _parse_func(source: str) -> ast.AsyncFunctionDef:
    """Parse a single async function definition from source."""
    module = ast.parse(textwrap.dedent(source))
    for node in module.body:
        if isinstance(node, ast.AsyncFunctionDef):
            return node
    raise ValueError(f"No AsyncFunctionDef found in source:\n{source}")


def _rewrite_body(func: ast.AsyncFunctionDef) -> list[ast.stmt]:
    """Apply _RecordingBodyRewriter to each body statement of func."""
    rewriter = _RecordingBodyRewriter()
    result = []
    for stmt in copy.deepcopy(func).body:
        new_stmt = rewriter.visit(stmt)
        ast.fix_missing_locations(new_stmt)
        result.append(new_stmt)
    return result


def _body_as_source(stmts: list[ast.stmt]) -> str:
    """Unparse a list of statements to a single source string."""
    return "\n".join(ast.unparse(s) for s in stmts)


# ---------------------------------------------------------------------------
# Test 1: self → self._parent rewrite at outermost position only
# ---------------------------------------------------------------------------


def test_rewriter_rewrites_self_to_self_parent_at_outermost_only() -> None:
    source = """\
async def foo(self):
    return self.hassette.registry.thing
"""
    func = _parse_func(source)
    rewritten = _rewrite_body(func)
    result = _body_as_source(rewritten)

    # The outermost self should become self._parent, and the chain continues
    assert "self._parent.hassette.registry.thing" in result
    # There should be no bare `self.hassette.` (the chain must go through _parent)
    assert "self.hassette." not in result
    # Exactly one _parent insertion at the leftmost position
    assert result.count("self._parent") == 1


# ---------------------------------------------------------------------------
# Test 2: await stripping
# ---------------------------------------------------------------------------


def test_rewriter_strips_await() -> None:
    source = """\
async def foo(self):
    return await self._get_raw_state("x")
"""
    func = _parse_func(source)
    rewritten = _rewrite_body(func)

    # No Await nodes should survive
    for stmt in rewritten:
        for node in ast.walk(stmt):
            assert not isinstance(node, ast.Await), f"Surviving Await found in: {ast.unparse(stmt)}"

    result = _body_as_source(rewritten)
    # self._get_raw_state should become self._parent._get_raw_state
    assert "self._parent._get_raw_state('x')" in result


# ---------------------------------------------------------------------------
# Test 3: default arguments untouched (Finding 9 regression test)
# ---------------------------------------------------------------------------


def test_rewriter_leaves_default_arguments_untouched() -> None:
    """The rewriter must NOT rewrite self.CONST in default argument expressions.

    This is the Finding 9 regression test. It exercises the production path
    (`gen_recording_method`), not just the lower-level `_rewrite_body` helper —
    the bug surface is the full method-emit pipeline, so the test must walk
    through it end-to-end. We assert the GENERATED SOURCE STRING contains
    `self.CONST` in the signature (untouched) but NOT `self._parent.CONST`.
    """
    source = """\
async def foo(self, x=self.CONST):
    return x
"""
    func = _parse_func(source)

    # Sanity check: original func has the self.CONST default
    defaults = func.args.defaults
    assert len(defaults) == 1
    assert "self.CONST" in ast.unparse(defaults[0])

    # Drive the production path — gen_recording_method is what the generator calls
    # for each body-copied method. async_method_names is empty here because foo
    # has no peer async calls; the static check should not fire.
    generated_source, _rewritten_body = gen_recording_method(func, async_method_names=set())

    # The generated SOURCE string must preserve self.CONST in the signature
    # and must NOT contain self._parent.CONST anywhere (signature or body).
    # `ast.unparse` may emit either `x=self.CONST` or `x = self.CONST` depending
    # on context (annotated args use spaces); normalize whitespace before checking.
    normalized = generated_source.replace(" ", "")
    assert "x=self.CONST" in normalized, f"Default argument was rewritten in generator output: {generated_source!r}"
    assert "self._parent.CONST" not in generated_source, (
        f"Default argument was incorrectly rewritten to _parent form: {generated_source!r}"
    )

    # The original func node must also be unchanged (we deep-copy before rewriting)
    default_src_after = ast.unparse(func.args.defaults[0])
    assert "self.CONST" in default_src_after
    assert "self._parent.CONST" not in default_src_after


# ---------------------------------------------------------------------------
# Test 4: lambda body self references are rewritten
# ---------------------------------------------------------------------------


def test_rewriter_rewrites_lambda_body_self_references() -> None:
    source = """\
async def foo(self, items):
    return list(filter(lambda item: self.predicate(item), items))
"""
    func = _parse_func(source)
    rewritten = _rewrite_body(func)
    result = _body_as_source(rewritten)

    # lambda body self.predicate should become self._parent.predicate
    assert "self._parent.predicate" in result
    # No bare self.predicate should remain
    assert "self.predicate" not in result.replace("self._parent.predicate", "")


# ---------------------------------------------------------------------------
# Test 5: static check raises on async peer call
# ---------------------------------------------------------------------------


def test_static_check_raises_on_async_peer_call() -> None:
    """gen_recording_method raises SystemExit when the body calls an async peer."""
    # foo calls self.bar() without await — but bar is async on RecordingApi.
    # After rewriting, this becomes self._parent.bar(), which the static check should catch.
    source = """\
async def foo(self):
    return self.bar()
"""
    func = _parse_func(source)
    # bar is async on our synthetic RecordingApi
    async_method_names = {"foo", "bar"}

    with pytest.raises(SystemExit) as exc_info:
        gen_recording_method(func, async_method_names)

    msg = str(exc_info.value)
    assert "foo" in msg
    assert "bar" in msg


# ---------------------------------------------------------------------------
# Test 6: static check allows sync helper calls
# ---------------------------------------------------------------------------


def test_static_check_allows_sync_helper_call() -> None:
    """gen_recording_method does NOT raise when the body calls a sync helper."""
    source = """\
async def get_state(self, entity_id: str):
    raw = self._get_raw_state(entity_id)
    return self._convert_state(raw, entity_id)
"""
    func = _parse_func(source)
    # _get_raw_state and _convert_state are regular defs (not in async_method_names)
    async_method_names: set[str] = {"get_state", "get_entity"}

    # Should not raise
    method_src, _ = gen_recording_method(func, async_method_names)
    assert "def get_state" in method_src


# ---------------------------------------------------------------------------
# Test 7: derive imports from body references
# ---------------------------------------------------------------------------


def test_derive_imports_from_body_references() -> None:
    """The production import-derivation pair (_collect_referenced_symbols +
    _build_precise_import_block) returns correct imports for type-like symbols
    (EntityNotFoundError, BaseState) referenced in a body, sourced from
    recording_api.py's import statements.
    """
    recording_source = _RECORDING_API_PATH.read_text(encoding="utf-8")
    symbol_map = _collect_module_level_import_map(recording_source)

    # Construct a synthetic body that references EntityNotFoundError and BaseState as Name nodes.
    # We use `model is BaseState` so BaseState appears as a plain ast.Name in the body.
    source = """\
async def foo(self, entity_id: str, model):
    try:
        raw = self._get_raw_state(entity_id)
    except EntityNotFoundError:
        return None
    if model is BaseState:
        return self._convert_state(raw, entity_id)
    return None
"""
    func = _parse_func(source)

    rewriter = _RecordingBodyRewriter()
    body_nodes = [rewriter.visit(copy.deepcopy(stmt)) for stmt in func.body]

    referenced = _collect_referenced_symbols(body_nodes)
    import_block = _build_precise_import_block(referenced, symbol_map)

    assert "EntityNotFoundError" in import_block
    assert "BaseState" in import_block


# ---------------------------------------------------------------------------
# Test 8: derive imports raises on unknown symbol
# ---------------------------------------------------------------------------


def test_derive_imports_raises_on_unknown_symbol() -> None:
    """_derive_recording_imports_strict raises SystemExit for unresolvable type-like symbols.

    Only uppercase-starting symbols are checked (they look like class/type references).
    Lowercase variable names are assumed to be local variables and skipped.
    """
    recording_source = _RECORDING_API_PATH.read_text(encoding="utf-8")
    symbol_map = _collect_module_level_import_map(recording_source)

    # Body references XUnknownTypeSymbol — an uppercase symbol not in recording_api.py imports.
    source = """\
async def foo(self):
    return XUnknownTypeSymbol()
"""
    func = _parse_func(source)

    rewriter = _RecordingBodyRewriter()
    body_nodes = [rewriter.visit(copy.deepcopy(stmt)) for stmt in func.body]

    with pytest.raises(SystemExit) as exc_info:
        _derive_recording_imports_strict(body_nodes, symbol_map, method_name="foo")

    msg = str(exc_info.value)
    assert "XUnknownTypeSymbol" in msg
    assert "no known import path" in msg


# ---------------------------------------------------------------------------
# Test 9: _format_via_ruff normalizes whitespace-differing inputs identically
# ---------------------------------------------------------------------------


def test_check_mode_normalizes_through_ruff() -> None:
    """_format_via_ruff produces byte-identical output for code differing only in whitespace."""
    # One version with extra blank lines and trailing whitespace
    content_messy = (
        "x = 1\n"
        "\n"
        "\n"
        "\n"
        "y = 2  \n"  # trailing whitespace
        "\n"
    )
    # The canonical form
    content_clean = "x = 1\n\n\ny = 2\n"

    normalized_messy = _format_via_ruff(content_messy)
    normalized_clean = _format_via_ruff(content_clean)

    assert normalized_messy == normalized_clean, (
        f"_format_via_ruff did not normalize to identical output.\n"
        f"Messy → {normalized_messy!r}\n"
        f"Clean → {normalized_clean!r}"
    )


# ---------------------------------------------------------------------------
# Test 10: end-to-end generate_sync_recording produces valid Python
# ---------------------------------------------------------------------------


def test_generate_recording_produces_valid_python() -> None:
    """Full generator run produces syntactically valid Python that py_compile accepts."""
    code = generate_sync_recording(_API_PATH, _RECORDING_API_PATH)

    # Write to a tempfile and compile
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        dir=tempfile.gettempdir(),
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        py_compile.compile(tmp_path, doraise=True)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
