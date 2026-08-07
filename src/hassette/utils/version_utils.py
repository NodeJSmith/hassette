from importlib.metadata import PackageNotFoundError, version

from packaging.version import Version

UNKNOWN_VERSION = "unknown"
FALLBACK_VERSION = "0.0.0"


def get_version() -> str:
    """Return the installed hassette package version, or 'unknown' if unavailable."""
    try:
        return version("hassette")
    except PackageNotFoundError:
        return UNKNOWN_VERSION


def get_parsed_version() -> Version:
    """Return the installed hassette package version as a `Version`.

    Falls back to `FALLBACK_VERSION` when package metadata is unavailable, since
    `UNKNOWN_VERSION` is not a valid PEP 440 version string.
    """
    version_str = get_version()
    return Version(version_str if version_str != UNKNOWN_VERSION else FALLBACK_VERSION)
