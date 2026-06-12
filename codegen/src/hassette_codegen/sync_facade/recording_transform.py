"""AST body rewriting and method generation for RecordingSyncFacade."""

import ast
import copy
import textwrap

from hassette_codegen.sync_facade.ast_utils import (
    STATE_CONVERSION_METHODS,
    format_signature_and_call,
    unwrap_coroutine_return,
)


class _RecordingBodyRewriter(ast.NodeTransformer):
    """Rewrite async body nodes for use in a synchronous facade.

    Two transforms:
    1. ``self.X`` → ``self._parent.X`` — only at the outermost position.
       ``self.hassette.foo`` becomes ``self._parent.hassette.foo``;
       the chain is left intact.
    2. ``await expr`` → ``expr`` — strips the Await wrapper.

    The transformer must be dispatched on individual ``FunctionDef.body``
    statements via ``self.visit(stmt)``, never on the whole FunctionDef node.
    This ensures default-argument expressions (which live in ``func.args``,
    not ``func.body``) are never rewritten.
    """

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        """Rewrite only the outermost self.X reference in attribute chains."""
        # First, recurse into all children so nested chains get rewritten.
        self.generic_visit(node)

        # After generic_visit, check if the direct value of THIS attribute
        # node is a plain `self` name — if so, insert `_parent` one level up.
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            # Replace self.X with self._parent.X
            new_value = ast.Attribute(
                value=ast.Name(id="self", ctx=ast.Load()),
                attr="_parent",
                ctx=ast.Load(),
            )
            ast.copy_location(new_value, node.value)
            node.value = new_value
        return node

    def visit_Await(self, node: ast.Await) -> ast.AST:
        """Strip the await, returning the inner expression."""
        # Recurse into the inner value first so self refs inside are rewritten.
        return self.visit(node.value)


def _check_no_async_peer_calls(
    method_name: str,
    body_nodes: list[ast.stmt],
    async_method_names: set[str],
) -> None:
    """Walk the rewritten body and raise SystemExit if any call targets an async peer.

    After self→self._parent rewriting, peer calls look like
    ``self._parent.foo(...)`` where ``foo`` is async. These would return
    a coroutine instead of a value in the sync facade.

    Args:
        method_name: Name of the method being body-copied (for error messages).
        body_nodes: Rewritten body statement list.
        async_method_names: Set of async method names on RecordingApi.
    """
    for stmt in body_nodes:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            # We're looking for self._parent.X(...)
            if not isinstance(callee, ast.Attribute):
                continue
            callee_value = callee.value
            if not (
                isinstance(callee_value, ast.Attribute)
                and isinstance(callee_value.value, ast.Name)
                and callee_value.value.id == "self"
                and callee_value.attr == "_parent"
            ):
                continue
            peer_name = callee.attr
            if peer_name in async_method_names:
                lineno = getattr(node, "lineno", "?")
                raise SystemExit(
                    f"Generator error: method `{method_name}` body-copies a call to "
                    f"`self._parent.{peer_name}()` at line {lineno}, but `{peer_name}` is "
                    f"an async def on RecordingApi. "
                    f"Refactor `RecordingApi.{method_name}` to call a sync helper "
                    f"(e.g. `_get_raw_state`, `_convert_state`) directly, or document "
                    f"why this method should be in the NotImplementedError stub tier."
                )


def gen_recording_method(
    func: ast.AsyncFunctionDef | ast.FunctionDef, async_method_names: set[str]
) -> tuple[str, list[ast.stmt]]:
    """Generate a sync method by body-copying and rewriting a RecordingApi async method.

    The function:
    1. Deep-copies the function AST (to avoid mutating the source).
    2. Dispatches _RecordingBodyRewriter on each BODY statement individually
       (never on func itself, preserving default-argument expressions).
    3. Checks for surviving ast.Await nodes (invariant).
    4. Checks for async peer calls (static check).
    5. Emits a sync def using the original signature + rewritten body.

    Args:
        func: The RecordingApi async function node.
        async_method_names: All async method names on RecordingApi (for peer-call check).

    Returns:
        Tuple of (generated_source_string, rewritten_body_nodes).
    """
    # Clone via deep copy to avoid mutating the parsed AST
    func_copy = copy.deepcopy(func)

    # Dispatch rewriter on each body statement individually — never on func_copy itself.
    rewriter = _RecordingBodyRewriter()
    rewritten_body: list[ast.stmt] = []
    for stmt in func_copy.body:
        new_stmt = rewriter.visit(stmt)
        ast.fix_missing_locations(new_stmt)
        rewritten_body.append(new_stmt)

    # Invariant check: no surviving ast.Await nodes
    for stmt in rewritten_body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Await):
                raise SystemExit(
                    f"Generator error: method `{func.name}` still contains an `await` expression "
                    f"after body rewriting. Add explicit `_get_raw_state`/`_convert_state` "
                    f"sync helpers to `RecordingApi.{func.name}` instead of awaiting async peers."
                )

    # Generator-time async-peer-call static check
    _check_no_async_peer_calls(func.name, rewritten_body, async_method_names)

    # Build the sync def source
    name = func.name
    # Unwrap Coroutine[Any, Any, T] → T for de-asynced plain-def methods.
    unwrapped = unwrap_coroutine_return(func)
    if unwrapped is not None:
        returns = f" -> {ast.unparse(unwrapped)}"
    elif func.returns:
        returns = f" -> {ast.unparse(func.returns)}"
    else:
        returns = ""

    # Build signature from the original (pre-copy) func so defaults stay as-is
    sig, _ = format_signature_and_call(func)

    doc = ast.get_docstring(func)
    if doc:
        doc_str = textwrap.indent('"""' + doc + '"""', " " * 8)
        doc_block = f"\n{doc_str}\n\n"
    else:
        doc_block = "\n"

    # Emit the body statements via ast.unparse
    body_lines = []
    # Skip the docstring (first stmt if it's an Expr/Constant) since we already handled it
    body_start = 1 if doc else 0
    for stmt in rewritten_body[body_start:]:
        unparsed = ast.unparse(stmt)
        body_lines.append(textwrap.indent(unparsed, " " * 8))

    if not body_lines:
        body_lines = ["        pass"]

    body_str = "\n".join(body_lines)

    method_src = f"    def {name}({sig}){returns}:{doc_block}{body_str}\n"

    return method_src, rewritten_body


def gen_recording_stub(func: ast.AsyncFunctionDef | ast.FunctionDef) -> str:
    """Emit a sync stub method raising NotImplementedError with tiered message.

    Args:
        func: The Api async function node (used for the signature).

    Returns:
        The generated method source string. Unlike ``gen_recording_method``,
        no rewritten body nodes are returned — stubs do not contribute body
        statements that the import-derivation pass needs to inspect.
    """
    name = func.name
    # Unwrap Coroutine[Any, Any, T] → T for de-asynced plain-def methods.
    unwrapped = unwrap_coroutine_return(func)
    if unwrapped is not None:
        returns = f" -> {ast.unparse(unwrapped)}"
    elif func.returns:
        returns = f" -> {ast.unparse(func.returns)}"
    else:
        returns = ""
    sig, _ = format_signature_and_call(func)

    # Emit a NotImplementedError using the module-level _STUB_MSG_* constant name.
    # We reference the constant by name (not value) so the generated file uses the
    # same constant that tests import, making message changes a single-location edit.
    msg_const = "STUB_MSG_STATE_CONVERSION" if name in STATE_CONVERSION_METHODS else "STUB_MSG_GENERIC"

    return f'    def {name}({sig}){returns}:\n        raise NotImplementedError({msg_const}.format(name="{name}"))\n'


def is_not_implemented_only(func: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    """Return True if the function body only calls not_implemented (plus optional docstring/raise).

    Such methods in RecordingApi exist solely to satisfy the async protocol —
    they should be treated as stubs in the generated facade, not body-copied.
    The rewriter would turn ``not_implemented(name)`` into ``self._parent.not_implemented(name)``
    which doesn't exist in the generated file.
    """
    body = func.body
    for stmt in body:
        # Skip docstrings
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            continue
        # Skip ``raise RuntimeError("unreachable")``
        if isinstance(stmt, ast.Raise):
            continue
        # A call to not_implemented(name) is an ast.Expr wrapping an ast.Call
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            if isinstance(call.func, ast.Name) and call.func.id == "not_implemented":
                continue
        # Anything else means the body is more complex
        return False
    return True
