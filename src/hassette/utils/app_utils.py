import importlib.machinery
import importlib.util
import inspect
import json
import sys
import traceback
import typing
from logging import getLogger
from pathlib import Path

from hassette import context
from hassette.app.utils import validate_app
from hassette.exceptions import (
    AppPrecheckFailedError,
    CannotOverrideFinalError,
    InvalidInheritanceError,
    UndefinedUserConfigError,
)
from hassette.types.types import AppDict, RawAppDict
from hassette.utils.exception_utils import get_short_traceback

if typing.TYPE_CHECKING:
    from types import ModuleType

    from hassette import AppConfig, HassetteConfig
    from hassette.app import App
    from hassette.config.classes import AppManifest

LOGGER = getLogger(__name__)
LOADED_CLASSES: "dict[tuple[str, str], type[App[AppConfig]]]" = {}
FAILED_TO_LOAD_CLASSES: "dict[tuple[str, str], Exception]" = {}

EXCLUDED_PATH_PARTS = ("site-packages", "importlib")


def run_apps_pre_check(config: "HassetteConfig") -> None:
    """Pre-check all apps to ensure they can be loaded correctly.

    This prevents us from spinning up the whole system and then having apps fail to load
    due to import errors, misconfiguration, etc.

    Args:
        config: The Hassette configuration containing app manifests.

    Raises:
        AppPrecheckFailedError: If any app fails to load correctly.
    """

    def _root_cause(exc: BaseException) -> BaseException:
        """Prefer __cause__ (explicit raise ... from ...), else __context__."""
        err = exc
        while getattr(err, "__cause__", None) is not None:
            err = err.__cause__  # pyright: ignore[reportOptionalMemberAccess]
        if getattr(err, "__cause__", None) is None and getattr(err, "__context__", None) is not None:
            err = err.__context__  # pyright: ignore[reportOptionalMemberAccess]

        if typing.TYPE_CHECKING:
            assert isinstance(err, BaseException)

        return err

    def _find_user_frame(exc: BaseException, app_dir: Path) -> traceback.FrameSummary | None:
        """
        Pick the most useful traceback frame:
        1) last frame inside the app's directory
        2) last frame not in site-packages/importlib/hassette
        3) final frame of the traceback
        """
        try:
            err = _root_cause(exc)
            tb_list = traceback.extract_tb(err.__traceback__)
            if not tb_list:
                return None

            app_dir_str = app_dir.as_posix()

            # 1) prefer frames inside the app dir
            for fr in reversed(tb_list):
                if fr.filename.replace("\\", "/").startswith(app_dir_str):
                    return fr

            # 2) otherwise prefer frames that aren't obviously noise
            for fr in reversed(tb_list):
                fn = fr.filename
                if "hassette" not in fn and not any(part in fn for part in EXCLUDED_PATH_PARTS):
                    return fr

            # 3) fallback: last frame
            return tb_list[-1]

        except Exception:
            # Ultra-defensive: never let error formatting throw
            LOGGER.error("Error selecting user frame: %s", traceback.format_exc(limit=1))
            return None

    def _log_compact_load_error(app_manifest: "AppManifest", exc: BaseException) -> None:
        fr = _find_user_frame(exc, app_manifest.app_dir)
        traceback_str = traceback.format_exception_only(type(exc), exc)[-1].strip()
        if fr:
            msg = "Failed to load app '%s':\n\t%s (at %s:%d)"
            LOGGER.error(
                msg,
                app_manifest.display_name,
                traceback_str,
                fr.filename,
                fr.lineno,
                stacklevel=2,
            )
        else:
            LOGGER.error(
                "Failed to load app '%s':\n%s",
                app_manifest.display_name,
                traceback_str,
                stacklevel=2,
            )

    ### actual precheck code starts here ###

    had_errors = False

    for app_manifest in config.app_manifests.values():
        if not app_manifest.enabled:
            continue

        if app_manifest.auto_loaded:
            # skip auto-detected apps; they were already checked during detection
            continue

        try:
            load_app_class_from_manifest(app_manifest=app_manifest)

        except CannotOverrideFinalError as e:
            # Already a great, app-aware message
            LOGGER.error("App %s: %s", app_manifest.display_name, e)
            had_errors = True

        except (UndefinedUserConfigError, InvalidInheritanceError):
            LOGGER.error(
                "Failed to load app '%s' due to bad configuration - check previous logs for details",
                app_manifest.display_name,
            )
            had_errors = True

        except Exception as e:
            _log_compact_load_error(app_manifest, e)
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

    config = app_dict.get("config", [])
    config = config if isinstance(config, list) else [config]

    clean_app_dict = AppDict(
        app_key=app_key,
        filename=app_dict["filename"],
        class_name=app_dict["class_name"],
        app_dir=Path(app_dict["app_dir"]),
        enabled=app_dict.get("enabled", True),
        config=config,
        auto_loaded=app_dict.get("auto_loaded", False),
        full_path=full_path,
    )

    return clean_app_dict


def autodetect_apps(app_dir: Path, known_paths: set[Path], exclude_dirs: set[str]) -> dict[str, AppDict]:
    """Auto-detect app manifests in the provided app directory.

    Args:
        app_dir: Directory to search for app manifests.
        known_paths: Set of paths that are already known/configured.

    Returns:
        Detected app manifests, keyed by app key.
    """
    from hassette.app import App, AppSync

    app_manifests: dict[str, AppDict] = {}

    py_files = app_dir.rglob("*.py")
    for py_file in py_files:
        full_path = py_file.resolve()
        if intersection := exclude_dirs.intersection(full_path.parts):
            LOGGER.debug(
                "Excluding auto-detected app at %s due to excluded directory %s",
                full_path,
                intersection,
            )
            continue
        if full_path in known_paths:
            LOGGER.debug(
                "Skipping auto-detected app at %s as it is already configured",
                full_path,
            )
            continue
        try:
            path_str, module = import_module(app_dir, py_file, app_dir.name)
            classes = inspect.getmembers(module, inspect.isclass)
            for class_name, cls in classes:
                class_module = cls.__module__
                # ensure the class is defined in this module
                if class_module != module.__name__:
                    continue
                if issubclass(cls, (App, AppSync)) and cls not in (App, AppSync):
                    app_key = f"{path_str}.{class_name}"
                    app_dict = AppDict(
                        filename=py_file.name,
                        class_name=class_name,
                        app_dir=app_dir,
                        app_key=app_key,
                        enabled=True,
                        auto_loaded=True,
                        full_path=full_path,
                        config=[],
                    )
                    app_manifests[app_key] = app_dict
                    LOGGER.info(
                        "Auto-detected app manifest: %s",
                        json.dumps(app_dict, default=str, indent=2),
                    )
        except Exception:
            LOGGER.error(
                "Failed to auto-detect app classes in '%s':\n%s",
                py_file,
                get_short_traceback(),
            )

    return app_manifests


def load_app_class_from_manifest(app_manifest: "AppManifest", force_reload: bool = False) -> "type[App[AppConfig]]":
    """Load the app class specified by the given manifest.

    Args:
        app_manifest: The app manifest.
        force_reload: Whether to force reloading the module if already loaded.

    Returns:
        The app class.
    """
    return load_app_class(
        app_dir=app_manifest.app_dir,
        module_path=app_manifest.full_path,
        class_name=app_manifest.class_name,
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
    cache_key = (str(module_path), class_name)
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
    cache_key = (str(module_path), class_name)
    return FAILED_TO_LOAD_CLASSES[cache_key]


def class_already_loaded(module_path: Path, class_name: str) -> bool:
    """Check if the given class is already loaded.

    Args:
        module_path: The full path to the app module file.
        class_name: The name of the app class.

    Returns:
        True if the class is already loaded, False otherwise.
    """
    cache_key = (str(module_path), class_name)
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
    cache_key = (str(module_path), class_name)
    return LOADED_CLASSES[cache_key]


def load_app_class(
    app_dir: Path,
    module_path: Path,
    class_name: str,
    display_name: str | None = None,
    force_reload: bool = False,
) -> "type[App[AppConfig]]":
    """Import the app's class with a canonical package/module identity so isinstance works.

    Args:
        app_dir: The root directory containing apps.
        module_path: The full path to the app module file.
        class_name: The name of the app class to load.
        display_name: Optional display name for logging.
        force_reload: Whether to force reloading the module if already loaded.

    Returns:
        The app class.
    """
    from hassette.app import App, AppSync

    display_name = display_name or class_name

    # cache keyed by (absolute file path, class name)
    cache_key = (str(module_path), class_name)

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

    config = context.get_hassette_config()

    # exceptions are caught below to cache failures, but are re-raised so the caller still receives them
    try:
        pkg_name = config.app_dir.name
        path_str, module = import_module(app_dir, module_path, pkg_name)
    except Exception as e:
        FAILED_TO_LOAD_CLASSES[cache_key] = e
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

    if app_class._import_exception:
        FAILED_TO_LOAD_CLASSES[cache_key] = app_class._import_exception
        raise FAILED_TO_LOAD_CLASSES[cache_key]

    try:
        app_class.app_config_cls = validate_app(app_class)
    except Exception as e:
        app_class._import_exception = e

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
    if pkg_name == "":
        return ".".join(parts)
    return ".".join([pkg_name, *parts])


def _ensure_on_sys_path(p: Path) -> None:
    """Ensure the given path is on sys.path for module resolution.

    Args:
        p: Directory to add to sys.path

    Note:
      - Will not add root directories (with <=1 parts) for safety.
    """

    p = p.resolve()
    if len(p.parts) <= 1:
        LOGGER.warning("Refusing to add root directory %s to sys.path", p)
        return

    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
