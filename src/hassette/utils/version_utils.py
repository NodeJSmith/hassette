from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    """Return the installed hassette package version, or 'unknown' if unavailable."""
    try:
        return version("hassette")
    except PackageNotFoundError:
        return "unknown"
