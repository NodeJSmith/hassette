"""Manifests for the test apps under ``tests/data/apps``."""

from pathlib import Path

from hassette.config.classes import AppManifest

TEST_APPS_PATH = Path(__file__).parent.parent / "data" / "apps"
"""The test apps under ``tests/data/apps``, which ``make_test_app_manifest`` points at."""


def make_test_app_manifest(
    app_key: str,
    filename: str,
    class_name: str,
    app_config: dict | list[dict] | None = None,
    *,
    enabled: bool = True,
    display_name: str | None = None,
) -> AppManifest:
    """An ``AppManifest`` for a test app in ``tests/data/apps``.

    ``app_config`` defaults to one instance named after ``app_key``, and ``display_name`` to ``class_name``.
    """
    return AppManifest(
        app_key=app_key,
        filename=filename,
        class_name=class_name,
        app_dir=TEST_APPS_PATH,
        app_config=app_config or {"instance_name": app_key},
        enabled=enabled,
        display_name=display_name or class_name,
        full_path=TEST_APPS_PATH / filename,
    )
