"""What counts as app code, and the operations a reload-all runs over it.

App code is every module whose file lies inside an app root, outside the directories the app scan skips and outside
any installed-package location. Eviction, the syntax precheck and the watcher's reload-all rule all read that one
definition (``is_app_code``), so a module evicted is exactly a module checked and watched.
"""

import ast
import sys
from collections.abc import Iterable, Mapping
from logging import getLogger
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

from hassette.utils.app_utils import APP_MODULES, APP_SCAN_EXCLUDE_DIRS, clear_app_module, remove_cached_bytecode
from hassette.utils.stack_frames import HASSETTE_PACKAGE_DIR

if TYPE_CHECKING:
    from hassette import HassetteConfig

LOGGER = getLogger(__name__)

INSTALLED_DIRS = tuple(
    dict.fromkeys(Path(p).resolve() for p in (sys.prefix, sys.base_prefix, sys.exec_prefix, HASSETTE_PACKAGE_DIR))
)
"""Locations whose modules are installed code, never app code: the interpreter prefixes and hassette itself,
the same set ``FrameClassifier`` excludes from stack-frame attribution."""


def app_roots(config: "HassetteConfig") -> frozenset[Path]:
    """The resolved app roots: ``apps.directory`` plus every manifest's ``app_dir``, enabled or not."""
    roots = {config.apps.directory.resolve()}
    roots.update(manifest.app_dir.resolve() for manifest in config.apps.manifests.values())
    return frozenset(roots)


def is_app_code(path: Path, roots: Iterable[Path]) -> bool:
    """Whether ``path`` is app code: inside an app root, not under a skipped directory or an installed location.

    Args:
        path: The file or directory to classify. Resolved here, so a symlinked app root still matches.
        roots: Resolved app roots, from ``app_roots``.
    """
    return is_resolved_app_code(path.resolve(), roots)


def is_resolved_app_code(resolved: Path, roots: Iterable[Path]) -> bool:
    """``is_app_code`` for a path that is already resolved."""
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


def app_code_modules(
    roots: Iterable[Path], modules: Mapping[str, ModuleType] | None = None
) -> dict[str, tuple[ModuleType, Path]]:
    """Every loaded module whose file is app code, with that resolved file, by module name.

    A module counts whatever name it was imported under. Each module directory is resolved once and classified as
    app code or not, so only the files in an app-code directory are resolved one by one: resolving every loaded
    module's file costs hundreds of milliseconds.

    Args:
        roots: Resolved app roots, from ``app_roots``.
        modules: The modules to scan, by name: a snapshot of ``sys.modules`` taken on the event loop when this
            runs in a worker thread, so the loop's imports can't change the mapping mid-scan. None reads
            ``sys.modules`` itself.
    """
    roots = tuple(roots)
    snapshot = sys.modules.copy() if modules is None else modules
    app_dirs: dict[Path, bool] = {}
    found: dict[str, tuple[ModuleType, Path]] = {}
    for name, module in snapshot.items():
        raw = getattr(module, "__file__", None)
        if not isinstance(raw, str):
            continue
        directory = Path(raw).parent
        if directory not in app_dirs:
            app_dirs[directory] = is_app_code(directory, roots)
        if not app_dirs[directory]:
            continue
        file = Path(raw).resolve()
        if is_resolved_app_code(file, roots):
            found[name] = (module, file)
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
    for name, (module, file) in modules.items():
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


def precheck_apps_package(
    roots: Iterable[Path], enabled_app_files: Iterable[Path], modules: Mapping[str, ModuleType] | None = None
) -> SyntaxError | None:
    """Compile every file a reload-all is about to import, and return the first syntax error.

    The files are those of the loaded app-code modules plus every enabled app's own file. A file that no longer
    exists is skipped: its importers fail at import instead, and that app goes FAILED. A file ``compile`` rejects
    with ``ValueError`` (a NUL byte, before Python 3.12) is reported as a ``SyntaxError`` too.

    Args:
        roots: Resolved app roots, from ``app_roots``.
        enabled_app_files: Every enabled app's own file.
        modules: The loaded modules to check, as for ``app_code_modules``.

    Returns:
        The first ``SyntaxError`` (by path), carrying its file and line, or None when every file compiles.
    """
    roots = tuple(roots)
    files = {file for _, file in app_code_modules(roots, modules).values()}
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
        except ValueError as exc:
            return SyntaxError(str(exc), (str(path), None, None, None))
    return None


def describe_syntax_error(exc: SyntaxError, roots: Iterable[Path]) -> str:
    """``<path>:<line>: <msg>``, with the path relative to the app root that contains it."""
    path = Path(exc.filename) if exc.filename else Path("<unknown>")
    for root in sorted(roots, key=lambda root: len(root.parts), reverse=True):
        if path.is_relative_to(root):
            path = path.relative_to(root)
            break
    return f"{path}:{exc.lineno or 0}: {exc.msg}"


def needs_reload_all(
    changed_paths: Iterable[Path],
    app_files: Iterable[Path],
    roots: Iterable[Path],
    modules: Mapping[str, ModuleType] | None = None,
) -> bool:
    """Whether a watcher change needs a reload-all rather than per-app reimports.

    True when a changed app-code ``.py`` file is not any app's own file (a helper), or is an app's file that
    another loaded app-code module imports, read from that module's ``import`` statements. A dynamic import
    (``importlib.import_module``) is invisible to this.

    Args:
        changed_paths: The paths the watcher reported.
        app_files: Every configured app's own file.
        roots: Resolved app roots, from ``app_roots``.
        modules: The loaded modules to read imports from, as for ``app_code_modules``.
    """
    roots = tuple(roots)
    own_files = {path.resolve() for path in app_files}
    changed = [path for path in changed_paths if path.suffix == ".py" and is_app_code(path, roots)]
    if any(path.resolve() not in own_files for path in changed):
        return True
    if not changed:
        return False
    loaded = app_code_modules(roots, modules)
    changed_files = {path.resolve() for path in changed}
    changed_names = {name for name, (_, file) in loaded.items() if file in changed_files}
    return any(
        file not in changed_files and imported_module_names(name, module) & changed_names
        for name, (module, file) in loaded.items()
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
    if node.level - 1 >= len(parts):
        return None
    base_parts = parts[: len(parts) - (node.level - 1)]
    if node.module:
        base_parts.append(node.module)
    return ".".join(base_parts)


def dotted_prefixes(name: str) -> list[str]:
    """``a.b.c`` -> ``["a", "a.b", "a.b.c"]``: importing a module imports each package above it."""
    parts = name.split(".")
    return [".".join(parts[: index + 1]) for index in range(len(parts))]
