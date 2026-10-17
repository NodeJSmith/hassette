"""Tests for runtime-detection helpers in ``hassette.config.helpers``."""

import pytest

from hassette.config.helpers import is_addon_runtime


class TestIsAddonRuntime:
    def test_addon_value_is_detected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HASSETTE_DOCKER_RUNTIME", "addon")
        assert is_addon_runtime() is True

    def test_unset_is_not_addon(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HASSETTE_DOCKER_RUNTIME", raising=False)
        assert is_addon_runtime() is False

    def test_other_runtime_is_not_addon(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HASSETTE_DOCKER_RUNTIME", "docker")
        assert is_addon_runtime() is False
