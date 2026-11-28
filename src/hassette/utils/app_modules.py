"""What counts as app code, and the operations a reload-all runs over it.

App code is every module whose file lies inside an app root, outside the directories the app scan skips and outside
any installed-package location. Eviction, the syntax precheck and the watcher's reload-all rule all read that one
definition (``is_app_code``), so a module evicted is exactly a module checked and watched.
"""

import ast
import sys
from collections.abc import Iterable
from logging import getLogger
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

from hassette.utils.app_utils import APP_MODULES, APP_SCAN_EXCLUDE_DIRS, clear_app_module, remove_cached_bytecode

if TYPE_CHECKING:
    from hassette import HassetteConfig

LOGGER = getLogger(__name__)

HASSETTE_PACKAGE_DIR = Path(__file__).resolve().parents[1]
"""Hassette's own package directory, never app code even when an app root contains it."""

INSTALLED_DIRS = tuple({Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(), HASSETTE_PACKAGE_DIR})
"""Locations whose modules are installed code, never app code: the interpreter prefixes and hassette itself."""


def app_roots(config: "HassetteConfig") -> frozenset[Path]:
    """The resolved app roots: ``apps.directory`` plus every manifest's ``app_dir``, enabled or not."""
    roots = {config.apps.directory.resolve()}
    roots.update(manifest.app_dir.resolve() for manifest in config.apps.manifests.values())
    return frozenset(roots)


def is_app_code(path: Path, roots: Iterable[Path]) -> bool:
    """Whether ``path`` is app code: inside an app root, not under a skipped directory or an installed location.

    Args:
        path: The file to classify. Resolved here, so a symlinked app root still matches.
        roots: Resolved app roots, from ``app_roots``.
    """
    resolved = path.resolve()
    if any(resolved.is_relative_to(installed) for installed in INSTALLED_DIRS):
        return False
    for root in roots:
        if resolved.is_relative_to(root) and not APP_SCAN_EXCLUDE_DIRS.intersection(resolved.relative_to(root).parts):
            return True
    return False


def module_file(module: ModuleType) -> Path | None:
    """The resolved file a module was loaded from, or None for a module without one (a namespace package)."""
    file = getattr(module, "__file__", None)
    return Path(file).resolve() if isinstance(file, str) else None


def app_code_modules(roots: Iterable[Path]) -> dict[str, ModuleType]:
    """Every ``sys.modules`` entry whose file is app code, by module name, whatever name it was imported under.

    App modules import from an app root's resolved path (the loader puts that on ``sys.path``), so a module whose
    raw ``__file__`` doesn't start with a root is skipped before the path is resolved: resolving every loaded
    module's file costs hundreds of milliseconds.
    """
    roots = tuple(roots)
    prefixes = tuple(str(root) for root in roots)
    found: dict[str, ModuleType] = {}
    for name, module in list(sys.modules.items()):
        raw = getattr(module, "__file__", None)
        if not isinstance(raw, str) or not raw.startswith(prefixes):
            continue
        file = module_file(module)
        if file is not None and is_app_code(file, roots):
            found[name] = module
    return found


def evict_apps_package(roots: Iterable[Path]) -> list[str]:
    """Remove every app-code module so the next import of each reads its file again.

    For each module in ``app_code_modules`` this removes its ``sys.modules`` entry and app record (through
    ``clear_app_module``), the attribute its parent package holds for it, and its cached bytecode. It then drops
    every app record left under the roots (a failed import has no module to find), so no app reuses a record from
    the old generation. Namespace packages have no file and stay, so later imports keep resolving under them.

    Returns:
        The evicted module names, sorted.
    """
    roots = tuple(roots)
    modules = app_code_modules(roots)
    record_paths = {record.name: path for path, record in APP_MODULES.items() if record.name is not None}
    for name, module in modules.items():
        file = module_file(module)
        if file is None:  # app_code_modules only returns modules with a file
            continue
        clear_app_module(record_paths.get(name, file), name)
        parent_name, _, child = name.rpartition(".")
        parent = sys.modules.get(parent_name) if parent_name else None
        if parent is not None and getattr(parent, child, None) is module:
            delattr(parent, child)
        if file.suffix == ".py":
            remove_cached_bytecode(file)
    for path, record in list(APP_MODULES.items()):
        if is_app_code(path, roots):
            clear_app_module(path, record.name)
    return sorted(modules)


def precheck_apps_package(roots: Iterable[Path], enabled_app_files: Iterable[Path]) -> SyntaxError | None:
    """Compile every file a reload-all is about to import, and return the first syntax error.

    The files are those of the loaded app-code modules plus every enabled app's own file. A file that no longer
    exists is skipped: its importers fail at import instead, and that app goes FAILED.

    Returns:
        The first ``SyntaxError`` (by path), carrying its file and line, or None when every file compiles.
    """
    roots = tuple(roots)
    files = {file for module in app_code_modules(roots).values() if (file := module_file(module)) is not None}
    files.update(path.resolve() for path in enabled_app_files)
    for path in sorted(file for file in files if file.suffix == ".py"):
        try:
            source = path.read_bytes()
        except OSError:
            continue
        try:
            compile(source, str(path), "exec", dont_inherit=True)
        except SyntaxError as exc:
            exc.filename = str(path)
            return exc
    return None


def describe_syntax_error(exc: SyntaxError, roots: Iterable[Path]) -> str:
    """``<path>:<line>: <msg>``, with the path relative to the app root that contains it."""
    path = Path(exc.filename) if exc.filename else Path("<unknown>")
    for root in sorted(roots, key=lambda root: len(root.parts), reverse=True):
        if path.is_relative_to(root):
            path = path.relative_to(root)
            break
    return f"{path}:{exc.lineno}: {exc.msg}"


def needs_reload_all(changed_paths: Iterable[Path], app_files: Iterable[Path], roots: Iterable[Path]) -> bool:
    """Whether a watcher change needs a reload-all rather than per-app reimports.

    True when a changed app-code ``.py`` file is not any app's own file (a helper), or is an app's file that
    another loaded app-code module imports, read from that module's ``import`` statements. A dynamic import
    (``importlib.import_module``) is invisible to this.

    Args:
        changed_paths: The resolved paths the watcher reported.
        app_files: Every configured app's own file.
        roots: Resolved app roots, from ``app_roots``.
    """
    roots = tuple(roots)
    own_files = {path.resolve() for path in app_files}
    changed = [path for path in changed_paths if path.suffix == ".py" and is_app_code(path, roots)]
    if any(path.resolve() not in own_files for path in changed):
        return True
    if not changed:
        return False
    loaded = app_code_modules(roots)
    changed_files = {path.resolve() for path in changed}
    changed_names = {name for name, module in loaded.items() if module_file(module) in changed_files}
    return any(
        module_file(module) not in changed_files and imported_module_names(name, module) & changed_names
        for name, module in loaded.items()
    )


def imported_module_names(name: str, module: ModuleType) -> set[str]:
    """The module names ``module``'s source imports anywhere in its body, relative imports resolved.

    ``import a.b`` names ``a`` and ``a.b``; ``from a import b`` names ``a`` and ``a.b``, since ``b`` may be a
    submodule. A file that can't be read or parsed names nothing.
    """
    file = module_file(module)
    if file is None or file.suffix != ".py":
        return set()
    try:
        tree = ast.parse(file.read_bytes(), filename=str(file))
    except (OSError, SyntaxError, ValueError):
        LOGGER.debug("Could not read the imports of %s (%s)", name, file, exc_info=True)
        return set()
    package = name if hasattr(module, "__path__") else name.rpartition(".")[0]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.update(dotted_prefixes(alias.name))
        elif isinstance(node, ast.ImportFrom):
            base = resolve_from_base(node, package)
            if base is None:
                continue
            if base:
                names.update(dotted_prefixes(base))
            names.update(f"{base}.{alias.name}" if base else alias.name for alias in node.names)
    return names


def resolve_from_base(node: ast.ImportFrom, package: str) -> str | None:
    """The absolute module a ``from ... import`` reads from, or None when its relative level climbs past the top."""
    if node.level == 0:
        return node.module or ""
    parts = package.split(".") if package else []
    if node.level - 1 > len(parts):
        return None
    base_parts = parts[: len(parts) - (node.level - 1)]
    if node.module:
        base_parts.append(node.module)
    return ".".join(base_parts)


def dotted_prefixes(name: str) -> list[str]:
    """``a.b.c`` -> ``["a", "a.b", "a.b.c"]``: importing a module imports each package above it."""
    parts = name.split(".")
    return [".".join(parts[: index + 1]) for index in range(len(parts))]
