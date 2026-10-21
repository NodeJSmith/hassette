import ast
import importlib.machinery
import importlib.util
import os
import sys
import traceback
import typing
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import Path

from pydantic.alias_generators import to_snake

from hassette.app.utils import validate_app
from hassette.config.defaults import APP_SCAN_EXCLUDE_DIRS
from hassette.exceptions import (
    AppPrecheckFailedError,
    CannotOverrideFinalError,
    InvalidInheritanceError,
    UndefinedUserConfigError,
)
from hassette.types.types import AppDict, RawAppDict

if typing.TYPE_CHECKING:
    from types import ModuleType

    from hassette import AppConfig, HassetteConfig
    from hassette.app import App
    from hassette.config.classes import AppManifest
    from hassette.config.models import AppsConfig

LOGGER = getLogger(__name__)
LOADED_CLASSES: "dict[tuple[str, str], type[App[AppConfig]]]" = {}
FAILED_TO_LOAD_CLASSES: "dict[tuple[str, str], Exception]" = {}

EXCLUDED_PATH_PARTS = ("site-packages", "importlib", "hassette")
APP_BASE_NAMES = frozenset({"App", "AppSync"})


@dataclass
class AppScan:
    """What the unconfigured-app scan found under an apps directory."""

    unconfigured: list[tuple[Path, str]] = field(default_factory=list)
    """``(file path, class name)`` for each app class no app entry configures."""

    unreadable: list[tuple[Path, str]] = field(default_factory=list)
    """``(file path, error message)`` for each ``.py`` file the scan skipped because reading, parsing, or
    resolving it failed."""


def app_cache_key(module_path: Path, class_name: str) -> tuple[str, str]:
    return (str(module_path), class_name)


def is_valid_instance_name(value: object) -> typing.TypeGuard[str]:
    """Whether a config-sourced ``instance_name`` value is usable.

    A single source of truth for "usable" so the pre-instantiation check in
    ``AppFactory.create_instances`` and the untracked-instance display fallback in
    ``AppRegistry._resolve_instance_name`` can't silently diverge on what counts as
    valid (e.g. one accepting a non-string truthy value like ``123`` that the other rejects).
    A ``TypeGuard`` so callers get ``str`` narrowing on the checked value, not just a bool.
    """
    return isinstance(value, str) and bool(value)


def root_cause(exc: BaseException) -> BaseException:
    """Prefer __cause__ (explicit raise ... from ...), else __context__."""
    err = exc
    while getattr(err, "__cause__", None) is not None:
        err = err.__cause__  # pyright: ignore[reportOptionalMemberAccess]
    if err is exc and getattr(err, "__context__", None) is not None:
        err = err.__context__  # pyright: ignore[reportOptionalMemberAccess]

    if typing.TYPE_CHECKING:
        assert isinstance(err, BaseException)

    return err


def find_user_frame(exc: BaseException, app_dir: Path) -> traceback.FrameSummary | None:
    """Pick the most useful traceback frame for an app load error.

    1) last frame inside the app's directory
    2) last frame not in site-packages/importlib/hassette
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

        for frame in reversed(tb_list):
            fn = frame.filename
            if not any(part in fn for part in EXCLUDED_PATH_PARTS):
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
    skipped, logged at DEBUG, and reported in ``unreadable``. Directories named in ``APP_SCAN_EXCLUDE_DIRS``
    are never entered, and an `app_dir` whose own absolute path contains one of those names isn't scanned.

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

    found: list[tuple[Path, str]] = []
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
            found.extend((path, name) for name in class_names if (resolved, name) not in configured)
    return AppScan(unconfigured=found, unreadable=unreadable)


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
    """The snake_case class name as an app key, or the first free ``_2``, ``_3``, ... variant of it."""
    base = to_snake(class_name)
    key, suffix = base, 2
    while key in taken:
        key = f"{base}_{suffix}"
        suffix += 1
    return key


def unconfigured_app_warning(app_dir: Path, path: Path, class_name: str, key: str) -> str:
    """The startup warning for one unconfigured app class, with an entry under `key` that loads it as pasted."""
    filename = path.relative_to(app_dir.resolve()).as_posix()
    return (
        f"App class {class_name} in {path} is not configured, so it won't run. To run it, add to your config:\n\n"
        f"[hassette.apps.{key}]\n"
        f'filename = "{filename}"\n'
        f'class_name = "{class_name}"\n\n'
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


def class_failed_to_load(module_path: Path, class_name: str) -> bool:
    """Check if the given class previously failed to load.

    Args:
        module_path: The full path to the app module file.
        class_name: The name of the app class.

    Returns:
        True if the class failed to load previously, False otherwise.
    """
    cache_key = app_cache_key(module_path, class_name)
    return cache_key in FAILED_TO_LOAD_CLASSES


def get_class_load_error(module_path: Path, class_name: str) -> Exception:
    """Get the exception that caused the given class to fail to load. Raises KeyError if the class loaded successfully.

    Args:
        module_path: The full path to the app module file.
        class_name: The name of the app class.

    Returns:
        The exception that caused the class to fail to load.

    Raises:
        KeyError: If the class loaded successfully.
    """
    cache_key = app_cache_key(module_path, class_name)
    return FAILED_TO_LOAD_CLASSES[cache_key]


def class_already_loaded(module_path: Path, class_name: str) -> bool:
    """Check if the given class is already loaded.

    Args:
        module_path: The full path to the app module file.
        class_name: The name of the app class.

    Returns:
        True if the class is already loaded, False otherwise.
    """
    cache_key = app_cache_key(module_path, class_name)
    return cache_key in LOADED_CLASSES


def get_loaded_class(module_path: Path, class_name: str) -> "type[App[AppConfig]]":
    """Get the loaded class for the given module path and class name. Raises KeyError if not loaded.

    Args:
        module_path: The full path to the app module file.
        class_name: The name of the app class.

    Returns:
        The loaded class.

    Raises:
        KeyError: If the class is not loaded.
    """
    cache_key = app_cache_key(module_path, class_name)
    return LOADED_CLASSES[cache_key]


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

    Args:
        app_dir: The root directory containing apps.
        module_path: The full path to the app module file.
        class_name: The name of the app class to load.
        config: The Hassette configuration, which names the apps package. Passed in rather than
            read from context because callers reach the loader from tasks that may not carry the
            Hassette contextvars, such as a web request or the startup pre-check.
        display_name: Optional display name for logging.
        force_reload: Whether to force reloading the module if already loaded.

    Returns:
        The app class.
    """
    from hassette.app import (  # house-lint: ignore[HSL002] - break circular import, hassette.app imports this module
        App,
        AppSync,
    )

    display_name = display_name or class_name

    # cache keyed by (absolute file path, class name)
    cache_key = app_cache_key(module_path, class_name)

    if force_reload:
        if cache_key in LOADED_CLASSES:
            LOGGER.info("Forcing reload of app class %s from %s", class_name, module_path)
            del LOADED_CLASSES[cache_key]
        if cache_key in FAILED_TO_LOAD_CLASSES:
            LOGGER.info("Forcing reload of previously failed app class %s from %s", class_name, module_path)
            del FAILED_TO_LOAD_CLASSES[cache_key]

    if cache_key in FAILED_TO_LOAD_CLASSES:
        raise FAILED_TO_LOAD_CLASSES[cache_key]

    if cache_key in LOADED_CLASSES:
        return LOADED_CLASSES[cache_key]

    if not module_path or not class_name:
        raise ValueError(f"App {display_name} is missing filename or class_name")

    # exceptions are caught below to cache failures, but are re-raised so the caller still receives them
    try:
        pkg_name = config.apps.directory.name
        path_str, module = import_module(app_dir, module_path, pkg_name)
    except Exception as exc:
        FAILED_TO_LOAD_CLASSES[cache_key] = exc
        raise

    try:
        app_class = getattr(module, class_name)
    except AttributeError:
        FAILED_TO_LOAD_CLASSES[cache_key] = AttributeError(
            f"Class {class_name} not found in module {path_str} ({module_path})"
        )
        raise FAILED_TO_LOAD_CLASSES[cache_key] from None

    if not issubclass(app_class, App | AppSync):
        FAILED_TO_LOAD_CLASSES[cache_key] = TypeError(f"Class {class_name} is not a subclass of App or AppSync")
        raise FAILED_TO_LOAD_CLASSES[cache_key]

    try:
        app_class.app_config_cls = validate_app(app_class)
    except Exception as exc:
        FAILED_TO_LOAD_CLASSES[cache_key] = exc
        raise

    LOADED_CLASSES[cache_key] = app_class
    return app_class


def import_module(app_dir: Path, module_path: Path, pkg_name: str) -> tuple[str, "ModuleType"]:
    """Import (or reload) a module from the given path under the 'apps' namespace package.

    Args:
        app_dir: The root directory containing apps.
        module_path: The full path to the app module file.
        pkg_name: The package name to use (e.g. 'apps')

    Returns:
        The formatted relative path and the imported module.
    """
    # specifically do not handle exceptions here, to let caller handle them

    _ensure_on_sys_path(app_dir)
    _ensure_on_sys_path(app_dir.parent)

    # 1) Ensure 'apps' is a namespace package pointing at app_config.app_dir
    _ensure_namespace_package(app_dir, pkg_name)

    # 2) Compute canonical module name from relative path under app_dir
    mod_name = _module_name_for(app_dir, module_path, pkg_name)

    # 3) Import or reload the module by canonical name
    if mod_name in sys.modules:
        module = importlib.reload(sys.modules[mod_name])
        return mod_name, module

    module = importlib.import_module(mod_name)
    return mod_name, module


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

    Each suggested key avoids configured keys, ``[hassette.apps]`` setting names, and earlier suggestions,
    so pasting every snippet gives a config that loads.
    """
    scan = AppScan()
    if apps.warn_unconfigured:
        configured = {(manifest.full_path, manifest.class_name) for manifest in apps.manifests.values()}
        scan = find_unconfigured_app_classes(apps.directory, configured)

    # raw entries include ones that failed validation; setting names share the [hassette.apps] table
    taken = {*apps.apps, *apps.manifests, *type(apps).model_fields}
    warnings: list[str] = []
    for path, class_name in scan.unconfigured:
        key = suggested_app_key(class_name, taken)
        taken.add(key)
        warnings.append(unconfigured_app_warning(apps.directory, path, class_name, key))

    has_apps = bool(apps.manifests) or bool(scan.unconfigured)
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
        warning += f". {len(unreadable)} {noun} could not be parsed:"
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
