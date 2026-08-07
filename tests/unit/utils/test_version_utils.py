"""Tests for hassette.utils.version_utils."""

from importlib.metadata import PackageNotFoundError

import pytest
from packaging.version import Version

from hassette.utils.version_utils import FALLBACK_VERSION, UNKNOWN_VERSION, get_parsed_version, get_version


def test_get_version_returns_installed_version() -> None:
    assert get_version() != UNKNOWN_VERSION


def test_get_version_returns_unknown_when_package_metadata_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_not_found(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr("hassette.utils.version_utils.version", raise_not_found)
    assert get_version() == UNKNOWN_VERSION


def test_get_parsed_version_falls_back_when_package_metadata_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hassette.utils.version_utils.get_version", lambda: UNKNOWN_VERSION)
    assert get_parsed_version() == Version(FALLBACK_VERSION)


def test_get_parsed_version_parses_real_version_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hassette.utils.version_utils.get_version", lambda: "1.2.3")
    assert get_parsed_version() == Version("1.2.3")
