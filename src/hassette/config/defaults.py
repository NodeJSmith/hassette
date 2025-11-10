import tomllib
from functools import lru_cache
from importlib.resources import files
from typing import Any

DEV_FILE = "hassette.dev.toml"
PROD_FILE = "hassette.prod.toml"
FILE_LOCATION = "hassette.config"
AUTODETECT_EXCLUDE_DIRS_DEFAULT = (".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".git")


@lru_cache
def get_defaults_from_toml(dev: bool = False) -> dict[str, Any]:
    """Get the default configuration from the TOML file.

    Args:
        dev: Whether to use development defaults.

    Returns:
        The default configuration dictionary.
    """
    file_name = DEV_FILE if dev else PROD_FILE
    toml_path = files(FILE_LOCATION).joinpath(file_name)
    with toml_path.open("rb") as f:
        data = tomllib.load(f)
    return data["hassette"]


def get_default_dict(dev: bool = False) -> dict[str, Any]:
    """Get the default configuration dictionary.

    Args:
        dev: Whether to use development defaults.

    Returns:
        The default configuration dictionary.
    """
    return get_defaults_from_toml(dev)
