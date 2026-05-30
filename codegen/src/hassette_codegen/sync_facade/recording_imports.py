"""Import derivation pipeline for RecordingSyncFacade generation."""

import ast

from hassette_codegen.sync_facade.ast_utils import BUILTIN_NAMES, WELL_KNOWN_NAMES, safe_parse


def collect_type_checking_import_map(source: str) -> dict[str, str]:
    """Build a symbol → import-statement-source map from TYPE_CHECKING blocks only.

    These symbols are only available at type-check time and must be placed in
    ``if typing.TYPE_CHECKING:`` blocks in the generated file.
    """
    module = safe_parse(source, "<source>")
    symbol_map: dict[str, str] = {}

    for node in module.body:
        if isinstance(node, ast.If):
            test = node.test
            is_type_checking = (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING") or (
                isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"
            )
            if not is_type_checking:
                continue
            # This IS a TYPE_CHECKING block — collect all imports inside
            for child in ast.walk(node):
                if child is node:
                    continue
                if isinstance(child, ast.ImportFrom):
                    stmt_source = ast.unparse(child)
                    for alias in child.names:
                        alias_name = alias.asname if alias.asname else alias.name
                        symbol_map[alias_name] = stmt_source

    return symbol_map


def collect_module_level_import_map(source: str) -> dict[str, str]:
    """Build a symbol → import-statement-source map from only module-level imports.

    For ``from X import A, B, C`` lines, each symbol is mapped individually to
    the whole import line. However, ``build_precise_import_block`` should be
    used when you need only the symbols actually required (to avoid emitting
    unused imports from multi-symbol import lines).

    This skips TYPE_CHECKING blocks and only includes imports at the module
    top level (not inside functions or classes).
    """
    module = safe_parse(source, "<source>")
    symbol_map: dict[str, str] = {}

    def _add_import_node(import_node: ast.ImportFrom | ast.Import) -> None:
        stmt_source = ast.unparse(import_node)
        for alias in import_node.names:
            alias_name = alias.asname if alias.asname else alias.name
            symbol_map[alias_name] = stmt_source

    for node in module.body:
        # Skip TYPE_CHECKING conditional blocks
        if isinstance(node, ast.If):
            test = node.test
            is_type_checking = (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING") or (
                isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"
            )
            if is_type_checking:
                continue
            # Non-TYPE_CHECKING if blocks: walk the subtree for any
            # `from X import Y` and bare `import X` statements (e.g.,
            # `if sys.version_info >= (3, 11): import tomllib`).
            for child in ast.walk(node):
                if child is node:
                    continue
                if isinstance(child, (ast.ImportFrom, ast.Import)):
                    _add_import_node(child)
        elif isinstance(node, (ast.ImportFrom, ast.Import)):
            _add_import_node(node)

    return symbol_map


def build_precise_import_block(
    needed_symbols: set[str],
    symbol_map: dict[str, str],
) -> str:
    """Build a minimal import block for exactly the needed_symbols.

    Unlike using the raw symbol_map (which emits entire multi-symbol import lines),
    this function reconstructs each import statement with ONLY the symbols that
    are actually needed. This avoids emitting unused imports from lines like
    ``from typing import TYPE_CHECKING, Any, ClassVar, Never, Protocol, cast``.

    For ``from X import A, B`` style: groups needed symbols by module path,
    emits one ``from X import <needed>`` per module.
    For bare ``import X`` style: emits the full line as-is.
    """
    # Parse each unique import line once to determine module path and names
    # key: module_path, value: set of (name, asname_or_None) tuples needed
    from_imports: dict[str, list[tuple[str, str | None]]] = {}
    bare_imports: set[str] = set()

    # Build a mapping from module path → {all_symbols → alias} from the symbol_map
    module_to_aliases: dict[str, dict[str, str | None]] = {}  # module_path → {name: asname}

    # Parse unique import lines
    seen_lines: set[str] = set()
    for sym, line in symbol_map.items():
        if sym not in needed_symbols:
            continue
        if line in seen_lines:
            continue
        seen_lines.add(line)
        try:
            parsed = ast.parse(line, mode="single")
        except SyntaxError:
            continue
        for stmt in ast.walk(parsed):
            if isinstance(stmt, ast.ImportFrom) and stmt.module:
                module = stmt.module
                if module not in module_to_aliases:
                    module_to_aliases[module] = {}
                for alias in stmt.names:
                    module_to_aliases[module][alias.name] = alias.asname
            elif isinstance(stmt, ast.Import):
                for _alias in stmt.names:
                    bare_imports.add(ast.unparse(stmt))

    # Now build precise from-imports: only emit the symbols we actually need
    for module_path, all_aliases in module_to_aliases.items():
        needed_for_module = [
            (name, asname)
            for name, asname in sorted(all_aliases.items())
            if (asname if asname else name) in needed_symbols
        ]
        if needed_for_module:
            if module_path not in from_imports:
                from_imports[module_path] = []
            from_imports[module_path].extend(needed_for_module)

    lines: list[str] = list(sorted(bare_imports))
    for module_path in sorted(from_imports.keys()):
        names_part = ", ".join(
            f"{name} as {asname}" if asname else name for name, asname in sorted(from_imports[module_path])
        )
        lines.append(f"from {module_path} import {names_part}")

    return "\n".join(lines)


def _collect_referenced_symbols(body_nodes: list[ast.stmt]) -> set[str]:
    """Walk body_nodes and collect all ast.Name ids, excluding builtins."""
    referenced: set[str] = set()
    for stmt in body_nodes:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name):
                referenced.add(node.id)
    referenced -= BUILTIN_NAMES
    referenced -= WELL_KNOWN_NAMES
    return referenced


def _derive_recording_imports_strict(  # pyright: ignore[reportUnusedFunction] — used by main project tests
    body_nodes: list[ast.stmt],
    symbol_map: dict[str, str],
    method_name: str = "<unknown>",
) -> str:
    """Strict variant of import derivation: raises on unknown type-like symbols.

    A "type-like symbol" is one that starts with an uppercase letter (classes,
    exceptions, type aliases), indicating it is likely an import rather than a
    local variable. Lowercase names are assumed to be local variables/parameters
    and are silently skipped.

    Used **only by the unit test for the error case**. Production generation
    uses ``build_precise_import_block`` directly (which is silently lenient
    about unknown symbols and emits only the lines for symbols it can resolve)
    because method bodies reference many lowercase symbols that are local
    variables, parameters, or comprehension targets — not imports.
    """
    referenced_symbols = _collect_referenced_symbols(body_nodes)
    # Only check uppercase-starting symbols (likely type/class references)
    type_like_symbols = {s for s in referenced_symbols if s and s[0].isupper()}

    import_lines: set[str] = set()
    for sym in type_like_symbols:
        if sym in symbol_map:
            import_lines.add(symbol_map[sym])
        else:
            raise SystemExit(
                f"Method `{method_name}` uses symbol `{sym}` with no known import path; "
                f"add `{sym}` to `recording_api.py`'s imports"
            )

    return "\n".join(sorted(import_lines))


def collect_annotation_symbols(func: ast.AsyncFunctionDef) -> tuple[set[str], set[str]]:
    """Collect Name ids from all type annotations in a function's signature and return type.

    Returns:
        Tuple of (runtime_symbols, string_ref_symbols):
        - runtime_symbols: Names used in non-quoted annotations (need direct imports).
        - string_ref_symbols: Names inside quoted string annotations (need TYPE_CHECKING imports).
    """
    runtime_symbols: set[str] = set()
    string_ref_symbols: set[str] = set()

    def _walk_annotation(annotation: ast.expr) -> None:
        for node in ast.walk(annotation):
            if isinstance(node, ast.Name):
                runtime_symbols.add(node.id)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # Quoted annotation — parse the string and collect names from it
                try:
                    inner = ast.parse(node.value, mode="eval")
                    for inner_node in ast.walk(inner):
                        if isinstance(inner_node, ast.Name):
                            string_ref_symbols.add(inner_node.id)
                except SyntaxError:
                    pass

    args = func.args
    all_args = args.posonlyargs + args.args + args.kwonlyargs
    if args.vararg:
        all_args = [*all_args, args.vararg]
    if args.kwarg:
        all_args = [*all_args, args.kwarg]

    for arg in all_args:
        if arg.annotation:
            _walk_annotation(arg.annotation)

    if func.returns:
        _walk_annotation(func.returns)

    return runtime_symbols, string_ref_symbols
