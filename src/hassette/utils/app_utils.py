import ast
import hashlib
import importlib.machinery
import importlib.util
import os
import re
import sys
import traceback
import typing
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import Path

from pydantic.alias_generators import to_snake

from hassette.app.utils import validate_init_method
from hassette.config.classes import INSTANCE_NAME_MAX_LENGTH
from hassette.exceptions import (
    AppPrecheckFailedError,
    CannotOverrideFinalError,
    InvalidInheritanceError,
    UndefinedUserConfigError,
)
from hassette.schemas.app_config_shape import configured_instance_names
from hassette.types.types import AppDict, RawAppDict
from hassette.utils.stack_frames import FrameClassifier

if typing.TYPE_CHECKING:
    from types import ModuleType

    from hassette import AppConfig, HassetteConfig
    from hassette.app import App
    from hassette.config.classes import AppManifest
    from hassette.config.models import AppsConfig

LOGGER = getLogger(__name__)

# Characters kept free under the instance-name length cap for a suggested key's ``_N`` suffix.
SUGGESTED_KEY_SUFFIX_ROOM = 8
APP_BASE_NAMES = frozenset({"App", "AppSync"})
APP_SCAN_EXCLUDE_DIRS = frozenset(
    {".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".git", "node_modules", "site-packages"}
)
"""Directory names the unconfigured-app scan never descends into, matched against absolute path parts."""


@dataclass
class AppScan:
    """What the unconfigured-app scan found under an apps directory."""

    unconfigured: list[tuple[Path, str]] = field(default_factory=list)
    """``(file path, class name)`` for each app class no app entry configures."""

    unreadable: list[tuple[Path, str]] = field(default_factory=list)
    """``(file path, error message)`` for each ``.py`` file the scan skipped because reading, parsing, or
    resolving it failed, or because it links to a file outside the apps directory."""


@dataclass
class AppModuleRecord:
    """What loading one app module produced: the module object, the classes read from it, and its failures.

    A record is current only while ``sys.modules`` maps ``name`` to ``module`` (for a failed import, while
    ``name`` is absent); a load that finds it stale imports again instead of trusting it. A failure recorded
    before the name was resolved (a missing file, say) has no name to check, so it stays current until a
    forced load retries it.
    """

    name: str | None
    """The module's canonical dotted name, or None when the load failed before the name was known."""

    module: "ModuleType | None"
    """The module object, or None after an import failure."""

    content_hash: str | None = None
    """SHA-256 of the file's bytes, read before the import that produced ``module``. None when this record
    adopted a module someone else imported, or after a failure, so a forced load always re-imports it."""

    classes: "dict[str, type[App[AppConfig]]]" = field(default_factory=dict)
    """The app classes read from ``module`` so far, by class name."""

    class_failures: dict[str, Exception] = field(default_factory=dict)
    """Why a class name failed: missing attribute, not an app class, or a failing ``validate_init_method``."""

    import_failure: Exception | None = None
    """The exception the import (or the read before it) raised; every class in the module fails with it."""

    def is_current(self) -> bool:
        """Whether ``sys.modules`` still holds the module this record describes."""
        current = sys.modules.get(self.name) if self.name is not None else None
        return current is self.module


APP_MODULES: dict[Path, AppModuleRecord] = {}
"""One record per app module file, keyed by the manifest's module path. Only ``clear_app_module`` removes one."""


def root_cause(exc: BaseException) -> BaseException:
    """Prefer __cause__ (explicit raise ... from ...), else __context__ unless suppressed (raise ... from None)."""
    err = exc
    while getattr(err, "__cause__", None) is not None:
        err = err.__cause__  # pyright: ignore[reportOptionalMemberAccess]
    if err is exc and not exc.__suppress_context__ and exc.__context__ is not None:
        err = exc.__context__

    if typing.TYPE_CHECKING:
        assert isinstance(err, BaseException)

    return err


def find_user_frame(exc: BaseException, app_dir: Path) -> traceback.FrameSummary | None:
    """Pick the most useful traceback frame for an app load error.

    1) last frame inside the app's directory
    2) last frame ``FrameClassifier`` treats as fallback user code (outside the interpreter,
       installed libraries, and hassette itself)
    3) final frame of the traceback
    """
    try:
        err = root_cause(exc)
        tb_list = traceback.extract_tb(err.__traceback__)
        if not tb_list:
            return None

        resolved_app_dir = app_dir.resolve()

        for frame in reversed(tb_list):
            try:
                if Path(frame.filename).resolve().is_relative_to(resolved_app_dir):
                    return frame
            except (ValueError, OSError):
                continue

        classifier = FrameClassifier.for_current_interpreter([resolved_app_dir])
        for frame in reversed(tb_list):
            if classifier.is_fallback_user_code(frame.filename):
                return frame

        return tb_list[-1]

    except Exception:
        LOGGER.error("Error selecting user frame: %s", traceback.format_exc(limit=1))
        return None


def log_compact_load_error(app_manifest: "AppManifest", exc: BaseException) -> None:
    """Log a compact, user-friendly error for a failed app load."""
    user_frame = find_user_frame(exc, app_manifest.app_dir)
    traceback_str = traceback.format_exception_only(type(exc), exc)[-1].strip()
    if user_frame:
        msg = "Failed to load app '%s':\n\t%s (at %s:%d)"
        LOGGER.error(
            msg,
            app_manifest.display_name,
            traceback_str,
            user_frame.filename,
            user_frame.lineno,
            stacklevel=2,
        )
    else:
        LOGGER.error(
            "Failed to load app '%s':\n%s",
            app_manifest.display_name,
            traceback_str,
            stacklevel=2,
        )


def run_apps_pre_check(config: "HassetteConfig") -> None:
    """Pre-check all apps to ensure they can be loaded correctly.

    Runs before system startup to surface import errors and misconfiguration
    early, without spinning up the full WebSocket/scheduler stack.

    Args:
        config: The Hassette configuration containing app manifests.

    Raises:
        AppPrecheckFailedError: If any app fails to load correctly.
    """
    had_errors = False

    for app_manifest in config.apps.manifests.values():
        if not app_manifest.enabled:
            continue

        try:
            load_app_class_from_manifest(app_manifest=app_manifest, config=config)

        except CannotOverrideFinalError as exc:
            LOGGER.error("App %s: %s", app_manifest.display_name, exc)
            had_errors = True

        except (UndefinedUserConfigError, InvalidInheritanceError) as exc:
            LOGGER.error("Failed to load app '%s' due to bad configuration: %s", app_manifest.display_name, exc)
            had_errors = True

        except Exception as exc:
            log_compact_load_error(app_manifest, exc)
            had_errors = True

    if had_errors:
        raise AppPrecheckFailedError("At least one app failed to load - see previous logs for details")


def clean_app(app_key: str, app_dict: RawAppDict, app_dir: Path) -> AppDict:
    """Normalize a raw app config entry into an ``AppDict``.

    Adds a ``.py`` extension when the filename has none, defaults ``app_dir`` to the given directory, resolves the
    app file's absolute filesystem path, wraps a single config in a list, and fills defaults for optional fields.

    Args:
        app_key: Key of the app entry in the configuration.
        app_dict: Raw app entry as read from the configuration; ``filename`` and ``app_dir`` are updated in place.
        app_dir: Directory to use when the entry does not set ``app_dir``.

    Returns:
        The normalized app entry.
    """
    filename = Path(app_dict["filename"])

    # handle missing file extensions
    if not filename.suffix:
        LOGGER.debug(
            "Filename %s for app %s has no extension, assuming .py",
            filename.name,
            app_key,
        )
        app_dict["filename"] = filename.with_suffix(".py").as_posix()

    if "app_dir" not in app_dict or not app_dict["app_dir"]:
        LOGGER.debug("Setting app_dir for app %s to %s", filename, app_dir)
        app_dict["app_dir"] = app_dir

    full_path = (Path(app_dict["app_dir"]) / app_dict["filename"]).resolve()

    app_configs = app_dict.get("config", [])
    app_configs = app_configs if isinstance(app_configs, list) else [app_configs]

    clean_app_dict = AppDict(
        app_key=app_key,
        filename=app_dict["filename"],
        class_name=app_dict["class_name"],
        app_dir=Path(app_dict["app_dir"]),
        enabled=app_dict.get("enabled", True),
        autostart=app_dict.get("autostart", True),
        config=app_configs,
        full_path=full_path,
        cache_key=app_dict.get("cache_key", ""),
        cache_shared=app_dict.get("cache_shared", False),
    )
    # Omitted when unset so AppManifest's own default (the app key) still applies.
    if display_name := app_dict.get("display_name"):
        clean_app_dict["display_name"] = display_name
    # Copied whenever present, so AppManifest validates (and rejects) whatever the config wrote.
    if "description" in app_dict:
        clean_app_dict["description"] = app_dict["description"]

    return clean_app_dict


def find_unconfigured_app_classes(app_dir: Path, configured: set[tuple[Path, str]]) -> AppScan:
    """Find app classes under `app_dir` that no app entry configures, without importing anything.

    Each ``.py`` file is parsed, not imported, so unconfigured files run no code. A class counts when it
    is defined at module top level and one of its bases, with any subscript stripped (``App[MyConfig]``),
    is the name ``App`` or ``AppSync`` or an attribute ending in one (``hassette.App``). Import aliases and
    indirect subclasses aren't resolved: the result is a newcomer hint, not a completeness check.

    Never raises: an unreadable directory is skipped, and a file that fails to read, parse, or resolve is
    skipped, logged at DEBUG, and reported in ``unreadable``, as is a symlink whose target is outside `app_dir`
    (no app entry could load it). Directories named in ``APP_SCAN_EXCLUDE_DIRS`` are never entered, and an
    `app_dir` whose own absolute path contains one of those names isn't scanned.

    Args:
        app_dir: The apps directory to scan.
        configured: ``(resolved file path, class name)`` pairs already configured by an app entry.

    Returns:
        The unconfigured classes and unreadable files, both in walk order: each directory's files sorted by
        name, then its subdirectories sorted by name, and classes in file order. Paths start with the
        resolved `app_dir` but aren't resolved themselves, so a warning can name them relative to `app_dir`.
    """
    root = app_dir.resolve()
    if not root.is_dir() or APP_SCAN_EXCLUDE_DIRS.intersection(root.parts):
        return AppScan()

    unconfigured: list[tuple[Path, str]] = []
    unreadable: list[tuple[Path, str]] = []
    # os.walk skips directories it can't read instead of raising
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in APP_SCAN_EXCLUDE_DIRS)
        for filename in sorted(f for f in filenames if f.endswith(".py")):
            path = Path(dirpath, filename)
            try:
                class_names = app_class_names(ast.parse(path.read_bytes(), filename=str(path)))
                # manifests hold resolved paths, so a symlinked file matches its configured target
                resolved = path.resolve()
            except Exception as exc:
                LOGGER.debug("Skipping %s in the unconfigured-app scan: %s", path, exc)
                # SyntaxError's str() repeats the file name the warning already shows
                error = f"{exc.msg} (line {exc.lineno})" if isinstance(exc, SyntaxError) else str(exc)
                unreadable.append((path, error))
                continue
            # an app entry can't name a file outside the apps directory, so a snippet for it couldn't load
            if not resolved.is_relative_to(root):
                error = f"links to {resolved}, outside the apps directory"
                LOGGER.debug("Skipping %s in the unconfigured-app scan: %s", path, error)
                unreadable.append((path, error))
                continue
            unconfigured.extend((path, name) for name in class_names if (resolved, name) not in configured)
    return AppScan(unconfigured=unconfigured, unreadable=unreadable)


def app_class_names(tree: ast.Module) -> list[str]:
    """Names of the module top-level classes whose bases visibly name ``App`` or ``AppSync``."""
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and any(is_app_base(base) for base in node.bases)
    ]


def is_app_base(base: ast.expr) -> bool:
    """Whether a class base is ``App``/``AppSync``, bare or as an attribute, with any subscript stripped."""
    if isinstance(base, ast.Subscript):
        base = base.value
    if isinstance(base, ast.Name):
        return base.id in APP_BASE_NAMES
    if isinstance(base, ast.Attribute):
        return base.attr in APP_BASE_NAMES
    return False


def suggested_app_key(class_name: str, taken: set[str]) -> str:
    """A key that is also a valid instance name, or the first free ``_2``, ``_3``, ... variant of it.

    The class name in snake_case, with characters outside the instance-name charset replaced by ``_``,
    an ``app_`` prefix when it doesn't start with a letter, and room left under the length cap for a suffix.
    """
    base = re.sub(r"[^a-z0-9_]", "_", to_snake(class_name)).strip("_")
    if not base[:1].isalpha():
        base = f"app_{base}".rstrip("_")
    base = base[: INSTANCE_NAME_MAX_LENGTH - SUGGESTED_KEY_SUFFIX_ROOM].rstrip("_")
    key, suffix = base, 2
    while key in taken:
        key = f"{base}_{suffix}"
        suffix += 1
    return key


def unconfigured_app_warning(app_dir: Path, path: Path, class_name: str, key: str) -> str:
    """The startup warning for one unconfigured app class, with an entry under `key` that loads it as pasted.

    The entry reuses `key` as the instance name, so callers pass a key no configured instance name uses either.
    """
    filename = path.relative_to(app_dir.resolve()).as_posix()
    return (
        f"App class {class_name} in {path} is not configured, so it won't run. To run it, add to your config:\n\n"
        f"[hassette.apps.{key}]\n"
        f'filename = "{filename}"\n'
        f'class_name = "{class_name}"\n'
        f'config = {{ instance_name = "{key}" }}\n\n'
        "If this is a base class, configure the apps that subclass it instead. "
        "Set warn_unconfigured = false under [hassette.apps] to turn this warning off."
    )


def load_app_class_from_manifest(
    app_manifest: "AppManifest", *, config: "HassetteConfig", force_reload: bool = False
) -> "type[App[AppConfig]]":
    """Load the app class specified by the given manifest.

    Args:
        app_manifest: The app manifest.
        config: The Hassette configuration, which names the apps package.
        force_reload: Whether to force reloading the module if already loaded.

    Returns:
        The app class.
    """
    return load_app_class(
        app_dir=app_manifest.app_dir,
        module_path=app_manifest.full_path,
        class_name=app_manifest.class_name,
        config=config,
        display_name=app_manifest.display_name,
        force_reload=force_reload,
    )


def current_module_record(module_path: Path) -> AppModuleRecord | None:
    """Return the module path's record if it still describes the module in ``sys.modules``, else None."""
    record = APP_MODULES.get(module_path)
    if record is None or not record.is_current():
        return None
    return record


def cached_class(module_path: Path, class_name: str) -> "type[App[AppConfig]] | None":
    """Return the class an earlier load read from the module, without importing anything.

    Args:
        module_path: The full path to the app module file.
        class_name: The name of the app class.

    Returns:
        The class, or None if no current load of the module produced it.
    """
    record = current_module_record(module_path)
    return record.classes.get(class_name) if record is not None else None


def cached_load_error(module_path: Path, class_name: str) -> Exception | None:
    """Return why an earlier load of the class failed, without importing anything.

    Args:
        module_path: The full path to the app module file.
        class_name: The name of the app class.

    Returns:
        The module's import failure, else the class's own failure, else None.
    """
    record = current_module_record(module_path)
    if record is None:
        return None
    if record.import_failure is not None:
        return record.import_failure
    return record.class_failures.get(class_name)


def clear_app_module(module_path: Path, mod_name: str | None) -> None:
    """Remove an app module from ``sys.modules`` and drop its record, together.

    The only code that removes app modules, so the class cache never outlives (or loses) its module.

    Args:
        module_path: The full path to the app module file.
        mod_name: The module's canonical dotted name, if known.
    """
    if mod_name is not None:
        sys.modules.pop(mod_name, None)
    APP_MODULES.pop(module_path, None)


def load_app_class(
    app_dir: Path,
    module_path: Path,
    class_name: str,
    *,
    config: "HassetteConfig",
    display_name: str | None = None,
    force_reload: bool = False,
) -> "type[App[AppConfig]]":
    """Import the app's class with a canonical package/module identity so isinstance works.

    A plain load imports the module at most once and reuses its record after that, failures included. A
    forced load re-imports the module only if its file changed since the last successful import, or that
    import failed (see ``load_module_record``).

    Args:
        app_dir: The root directory containing apps.
        module_path: The full path to the app module file.
        class_name: The name of the app class to load.
        config: The Hassette configuration, which names the apps package. Passed in rather than
            read from context because callers reach the loader from tasks that may not carry the
            Hassette contextvars, such as a web request or the startup pre-check.
        display_name: Optional display name for logging.
        force_reload: Whether to re-import the module if its file changed since it was imported.

    Returns:
        The app class.
    """
    display_name = display_name or class_name
    if not module_path or not class_name:
        raise ValueError(f"App {display_name} is missing filename or class_name")

    record = load_module_record(app_dir, module_path, config.apps.directory.name, force_reload=force_reload)
    return read_app_class(record, module_path, class_name)


def load_module_record(app_dir: Path, module_path: Path, pkg_name: str, *, force_reload: bool) -> AppModuleRecord:
    """Return the record for an app module, importing it under the apps namespace package when needed.

    A plain load reuses a current record as it is. Otherwise it calls ``importlib.import_module``, which
    imports the module or returns the one already in ``sys.modules``; only a module this call imported gets a
    content hash. A forced load reuses the record only when its last import succeeded and the file's hash
    still matches; otherwise it removes the module, deletes its cached bytecode, and imports it fresh.

    A failure is recorded and re-raised; the module is not restored to ``sys.modules``.

    Args:
        app_dir: The root directory containing apps.
        module_path: The full path to the app module file.
        pkg_name: The package name to use (e.g. 'apps')
        force_reload: Whether to re-import the module if its file changed or its last import failed.

    Returns:
        The module's current record.
    """
    record = APP_MODULES.get(module_path)
    if not force_reload and record is not None and record.is_current():
        return record

    mod_name: str | None = None
    try:
        _ensure_on_sys_path(app_dir)
        _ensure_on_sys_path(app_dir.parent)
        _ensure_namespace_package(app_dir, pkg_name)
        mod_name = _module_name_for(app_dir, module_path, pkg_name)
        # read before importing, so a save racing the import costs one extra re-import, never a stale hash
        content_hash = file_content_hash(module_path)

        if force_reload:
            if record is not None and unchanged_since_import(record, content_hash):
                LOGGER.info(
                    "Forced reload of %s: file unchanged (sha256 %s), reusing the loaded module",
                    mod_name,
                    content_hash[:12],
                )
                return record
            LOGGER.info("Forced reload of %s: re-importing %s (sha256 %s)", mod_name, module_path, content_hash[:12])
            clear_app_module(module_path, mod_name)
            remove_cached_bytecode(module_path)

        # A module already in sys.modules was imported by someone else (another app module's import), so its
        # bytes may predate this hash. Only possible on a plain load: a forced load just removed it.
        imported_here = mod_name not in sys.modules
        module = importlib.import_module(mod_name)
    except Exception as exc:
        if force_reload:
            # a failure before the eviction (an unreadable or deleted file) must not leave the old module to be
            # adopted; a deleted file fails before its name resolves, so fall back to the previous record's name
            clear_app_module(module_path, mod_name or (record.name if record is not None else None))
        APP_MODULES[module_path] = AppModuleRecord(name=mod_name, module=None, import_failure=exc)
        raise

    record = AppModuleRecord(name=mod_name, module=module, content_hash=content_hash if imported_here else None)
    APP_MODULES[module_path] = record
    return record


def unchanged_since_import(record: AppModuleRecord, content_hash: str) -> bool:
    """Whether a record's module was imported here from bytes hashing to ``content_hash`` and is still loaded."""
    return record.import_failure is None and record.content_hash == content_hash and record.is_current()


def read_app_class(record: AppModuleRecord, module_path: Path, class_name: str) -> "type[App[AppConfig]]":
    """Return the named app class from a module record, checking and caching it on first read.

    Raises:
        Exception: The module's import failure, or why the class is unusable (cached on the record).
    """
    # house-lint: ignore-next[HSL002] - break circular import, hassette.app imports this module
    from hassette.app import (  # noqa: PLC0415
        App,
        AppSync,
    )

    if record.import_failure is not None:
        raise record.import_failure
    if (app_class := record.classes.get(class_name)) is not None:
        return app_class
    if (failure := record.class_failures.get(class_name)) is not None:
        raise failure

    try:
        try:
            app_class = getattr(record.module, class_name)
        except AttributeError:
            raise AttributeError(f"Class {class_name} not found in module {record.name} ({module_path})") from None
        if not (isinstance(app_class, type) and issubclass(app_class, App | AppSync)):
            raise TypeError(f"Class {class_name} is not a subclass of App or AppSync")
        validate_init_method(app_class)
    except Exception as exc:
        record.class_failures[class_name] = exc
        raise

    record.classes[class_name] = app_class
    return app_class


def file_content_hash(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's bytes."""
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def remove_cached_bytecode(module_path: Path) -> None:
    """Delete the module's ``__pycache__`` file so the next import compiles the current source.

    The source loader trusts a ``.pyc`` whose recorded mtime (whole seconds) and size match the file, so a
    same-size edit saved within a second of the last compile would otherwise import the old code.
    """
    pyc = Path(importlib.util.cache_from_source(str(module_path.resolve())))
    try:
        pyc.unlink(missing_ok=True)
    except OSError as exc:
        LOGGER.warning(
            "Could not remove cached bytecode %s before re-importing %s; the import may use stale bytecode: %s",
            pyc,
            module_path,
            exc,
        )


def _ensure_namespace_package(root: Path, pkg_name: str) -> None:
    """Ensure a namespace package rooted at `root` is importable as `pkg_name`.

    Args:
        root: Directory to treat as the root of the namespace package.
        pkg_name: The package name to use (e.g. 'apps')

    Behavior:
    ---------
    - Creates/updates sys.modules[pkg_name] as a namespace package.
    - Adds `root` to submodule_search_locations so 'pkg_name.*' resolves under this directory.
    """
    root = root.resolve()
    if pkg_name in sys.modules and hasattr(sys.modules[pkg_name], "__path__"):
        ns_pkg = sys.modules[pkg_name]
        # extend search locations if necessary
        if str(root) not in ns_pkg.__path__:
            ns_pkg.__path__.append(str(root))
        return

    # Synthesize a namespace package
    spec = importlib.machinery.ModuleSpec(pkg_name, loader=None, is_package=True)
    ns_pkg = importlib.util.module_from_spec(spec)
    ns_pkg.__path__ = [str(root)]
    sys.modules[pkg_name] = ns_pkg


def _module_name_for(app_dir: Path, full_path: Path, pkg_name: str) -> str:
    """Map a file within app_dir to a stable module name under the 'apps' package.

    Args:
        app_dir: The root directory containing apps (e.g. /path/to/apps)
        full_path: The full path to the app module file (e.g. /path/to/apps/my_app.py)
        pkg_name: The package name to use (e.g. 'apps')

    Returns:
        The dotted module name (e.g. 'apps.my_app')

    Examples:
      app_dir=/path/to/apps
        /path/to/apps/my_app.py         -> apps.my_app
        /path/to/apps/notifications/email_digest.py -> apps.notifications.email_digest
    """
    if not full_path.exists():
        raise FileNotFoundError(f"Module path does not exist: {full_path}")

    if full_path.is_dir():
        raise IsADirectoryError(f"Module path is a directory, expected a file: {full_path}")

    app_dir = app_dir.resolve()
    full_path = full_path.resolve()

    rel = full_path.relative_to(app_dir).with_suffix("")  # drop .py
    parts = list(rel.parts)
    if not pkg_name:
        return ".".join(parts)
    return ".".join([pkg_name, *parts])


def _ensure_on_sys_path(dir_path: Path) -> None:
    """Ensure the given path is on sys.path for module resolution.

    Args:
        dir_path: Directory to add to sys.path

    Note:
      - Will not add root directories (with <=1 parts) for safety.
    """
    dir_path = dir_path.resolve()
    if len(dir_path.parts) <= 1:
        LOGGER.warning("Refusing to add root directory %s to sys.path", dir_path)
        return

    if str(dir_path) not in sys.path:
        sys.path.insert(0, str(dir_path))


def app_startup_warnings(apps: "AppsConfig", *, config_files: Iterable[Path], cwd: Path) -> list[str]:
    """Return the startup warnings about the apps directory and the apps found in it.

    One warning per unconfigured app class (when ``apps.warn_unconfigured`` is set), then the missing- or
    empty-directory warning. Unconfigured classes count as apps for the empty-directory check, so a
    newcomer whose only app lacks an entry sees that cause alone, not "No apps found" as well; files the
    scan couldn't parse are named in "No apps found", since a broken app file is its likeliest cause. With
    ``warn_unconfigured`` off the scan doesn't run, so a directory holding only unconfigured classes
    gets "No apps found".

    Each suggested key avoids configured keys, configured instance names, ``[hassette.apps]`` setting names,
    and earlier suggestions. The snippet uses the key as its instance name too, so pasting every snippet gives
    a config that loads.
    """
    scan = AppScan()
    if apps.warn_unconfigured:
        configured = {(manifest.full_path, manifest.class_name) for manifest in apps.manifests.values()}
        scan = find_unconfigured_app_classes(apps.directory, configured)

    # raw entries include ones that failed validation; setting names share the [hassette.apps] table
    taken = {*apps.apps, *apps.manifests, *type(apps).model_fields}
    taken.update(
        name for manifest in apps.manifests.values() for name in configured_instance_names(manifest.app_config)
    )
    warnings: list[str] = []
    for path, class_name in scan.unconfigured:
        key = suggested_app_key(class_name, taken)
        taken.add(key)
        warnings.append(unconfigured_app_warning(apps.directory, path, class_name, key))

    has_apps = bool(apps.manifests or scan.unconfigured)
    if warning := apps_dir_warning(
        apps.directory, has_apps=has_apps, config_files=config_files, cwd=cwd, unreadable=scan.unreadable
    ):
        warnings.append(warning)
    return warnings


def apps_dir_warning(
    apps_dir: Path,
    *,
    has_apps: bool,
    config_files: Iterable[Path],
    cwd: Path,
    unreadable: Sequence[tuple[Path, str]] = (),
) -> str | None:
    """Return the startup warning for an apps directory that is missing or holds no apps, else None.

    The no-apps warning names each `unreadable` file (``(path, error)`` from the scan) and why it failed.
    """
    if warning := missing_apps_dir_warning(apps_dir, config_files=config_files, cwd=cwd):
        return warning
    if has_apps:
        return None
    warning = f"No apps found or configured in apps directory {apps_dir}"
    if unreadable:
        root = apps_dir.resolve()
        noun = "file" if len(unreadable) == 1 else "files"
        warning += f". {len(unreadable)} {noun} could not be scanned:"
        warning += "".join(f"\n  {path.relative_to(root).as_posix()}: {error}" for path, error in unreadable)
    return warning


def missing_apps_dir_warning(apps_dir: Path, *, config_files: Iterable[Path], cwd: Path) -> str | None:
    """Return the warning for an apps directory that doesn't exist, else None.

    The warning also names the directory the same relative path reaches from `cwd`, if one exists:
    a path written in one of `config_files` is relative to that file's directory, and reading it
    from the launch directory instead is the likeliest mistake.
    """
    if apps_dir.is_dir():
        return None
    warning = f"Apps directory {apps_dir} does not exist"
    if hint := cwd_relative_hint(apps_dir, sorted({path.parent for path in config_files}), cwd):
        warning += f". {hint}"
    return warning


def cwd_relative_hint(apps_dir: Path, config_file_dirs: Iterable[Path], cwd: Path) -> str | None:
    """Name the existing directory `apps_dir`'s path reaches when read from `cwd` instead of a file's directory."""
    for file_dir in config_file_dirs:
        relative = os.path.relpath(apps_dir, file_dir)
        candidate = Path(os.path.normpath(cwd / relative))
        if candidate != apps_dir and candidate.is_dir():
            return (
                f"Did you mean {candidate}? A path in a config file is relative to that file's directory, "
                f"so from {file_dir} it is written {os.path.relpath(candidate, file_dir)}"
            )
    return None
