"""Unit tests for web API auth token resolution: explicit config, existing token file,
freshly generated token, corrupt-file recovery, and distinct per-branch logging.
"""

import logging
import stat
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from hassette.config.models import WebApiConfig
from hassette.exceptions import AuthTokenWriteError
from hassette.web.auth.tokens import TOKEN_FILENAME, resolve_auth_token


def _make_config(**overrides: Any) -> WebApiConfig:
    return WebApiConfig.model_validate(overrides)


@pytest.fixture(autouse=True)
def _propagate_hassette_logger() -> None:
    """Ensure the "hassette" logger propagates so caplog can see records.

    Some other test in the session may have left ``propagate`` set to False (e.g. via
    ``enable_basic_logging()``); caplog relies on propagation to the root logger. Same
    workaround as ``tests/unit/test_validate_apps.py``.
    """
    logging.getLogger("hassette").propagate = True


class TestResolveAuthTokenExplicitConfig:
    def test_uses_configured_token_without_touching_disk(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = _make_config(auth_token=SecretStr("configured-token-value"))

        with caplog.at_level("INFO", logger="hassette.web.auth.tokens"):
            token = resolve_auth_token(config, tmp_path)

        assert token == "configured-token-value"
        assert not (tmp_path / TOKEN_FILENAME).exists()

        messages = [r.message for r in caplog.records]
        assert any("configured" in m.lower() for m in messages), messages

    @pytest.mark.parametrize("blank_value", ["", "   ", "\t\n"])
    def test_blank_configured_token_falls_back_to_generation(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, blank_value: str
    ) -> None:
        config = _make_config(auth_token=SecretStr(blank_value))

        with caplog.at_level("INFO", logger="hassette.web.auth.tokens"):
            token = resolve_auth_token(config, tmp_path)

        assert token != blank_value
        assert len(token) > 32  # secrets.token_urlsafe(32) produces a 43-char string
        assert (tmp_path / TOKEN_FILENAME).exists()

        messages = [r.message for r in caplog.records]
        assert any("blank" in m.lower() for m in messages), messages
        assert any("generated" in m.lower() for m in messages), messages


class TestResolveAuthTokenExistingFile:
    def test_loads_existing_token_file(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        token_path = tmp_path / TOKEN_FILENAME
        token_path.write_text("existing-token-value\n", encoding="utf-8")
        config = _make_config()

        with caplog.at_level("INFO", logger="hassette.web.auth.tokens"):
            token = resolve_auth_token(config, tmp_path)

        assert token == "existing-token-value"

        messages = [r.message for r in caplog.records]
        assert any("existing" in m.lower() and str(token_path) in m for m in messages), messages


class TestResolveAuthTokenGenerated:
    def test_generates_persists_and_logs_url(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        config = _make_config(host="127.0.0.1", port=8126)

        with caplog.at_level("INFO", logger="hassette.web.auth.tokens"):
            token = resolve_auth_token(config, tmp_path)

        token_path = tmp_path / TOKEN_FILENAME
        assert token_path.exists()
        assert token_path.read_text(encoding="utf-8") == token
        assert len(token) > 32  # secrets.token_urlsafe(32) produces a 43-char string

        mode = stat.S_IMODE(token_path.stat().st_mode)
        assert mode == 0o600, f"expected mode 0600, got {oct(mode)}"

        messages = [r.message for r in caplog.records]
        generated_messages = [m for m in messages if "generated" in m.lower()]
        assert generated_messages, messages
        assert any("http://127.0.0.1:8126" in m for m in generated_messages), generated_messages

    @pytest.mark.parametrize(
        ("configured_host", "expected_host_in_url"),
        [
            ("0.0.0.0", "127.0.0.1"),
            ("::", "[::1]"),
        ],
    )
    def test_bind_all_host_logs_dialable_login_url(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        configured_host: str,
        expected_host_in_url: str,
    ) -> None:
        """A bind-all ``host`` (0.0.0.0/::) must not appear verbatim in the logged login URL —
        an operator can't dial it. Regression test for the substitution `resolve_auth_token`
        applies via `hassette.utils.net_utils.format_host`.
        """
        config = _make_config(host=configured_host, port=8126)

        with caplog.at_level("INFO", logger="hassette.web.auth.tokens"):
            resolve_auth_token(config, tmp_path)

        messages = [r.message for r in caplog.records]
        generated_messages = [m for m in messages if "generated" in m.lower()]
        assert generated_messages, messages
        assert any(f"http://{expected_host_in_url}:8126" in m for m in generated_messages), generated_messages
        assert not any(f"http://{configured_host}:8126" in m for m in generated_messages), generated_messages

    def test_no_leftover_temp_file(self, tmp_path: Path) -> None:
        config = _make_config()
        resolve_auth_token(config, tmp_path)

        remaining = {p.name for p in tmp_path.iterdir()}
        assert remaining == {TOKEN_FILENAME}, remaining

    def test_write_failure_raises_named_exception(self, tmp_path: Path) -> None:
        config = _make_config()

        with (
            patch("hassette.web.auth.tokens.os.open", side_effect=OSError("disk full")),
            pytest.raises(AuthTokenWriteError) as exc_info,
        ):
            resolve_auth_token(config, tmp_path)

        err = exc_info.value
        assert err.path == tmp_path / TOKEN_FILENAME
        assert isinstance(err.original_error, OSError)
        assert str(tmp_path / TOKEN_FILENAME) in str(err)
        assert "disk full" in str(err)

        # No token file should have been left behind by the failed write.
        assert not (tmp_path / TOKEN_FILENAME).exists()


class TestResolveAuthTokenCorruptFile:
    def test_empty_file_falls_back_to_generation(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        token_path = tmp_path / TOKEN_FILENAME
        token_path.write_text("", encoding="utf-8")
        config = _make_config()

        with caplog.at_level("INFO", logger="hassette.web.auth.tokens"):
            token = resolve_auth_token(config, tmp_path)

        assert token  # a fresh token was generated
        assert token_path.read_text(encoding="utf-8") == token

        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert error_records, "expected an ERROR log line for the corrupt/empty token file"
        assert any(str(token_path) in r.message for r in error_records), [r.message for r in error_records]

        # Resolution still succeeds and reaches the "generated" branch, not a crash.
        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert any("generated" in r.message.lower() for r in info_records), [r.message for r in info_records]

    def test_undecodable_content_falls_back_to_generation(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        token_path = tmp_path / TOKEN_FILENAME
        token_path.write_bytes(b"\xff\xfe\x00garbage-not-utf8")
        config = _make_config()

        with caplog.at_level("ERROR", logger="hassette.web.auth.tokens"):
            token = resolve_auth_token(config, tmp_path)

        assert token
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert error_records, "expected an ERROR log line for undecodable token file content"

    def test_corrupt_file_does_not_raise(self, tmp_path: Path) -> None:
        """Resolution succeeds (returns) rather than propagating an exception."""
        token_path = tmp_path / TOKEN_FILENAME
        token_path.write_text("", encoding="utf-8")
        config = _make_config()

        token = resolve_auth_token(config, tmp_path)

        assert isinstance(token, str)
        assert token


class TestResolveAuthTokenDistinctLogMessages:
    def test_all_three_branches_produce_distinct_messages(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Each resolution branch logs a distinct, identifiable INFO message."""
        messages: list[str] = []

        with caplog.at_level("INFO", logger="hassette.web.auth.tokens"):
            resolve_auth_token(_make_config(auth_token=SecretStr("explicit-value")), tmp_path / "a")
        messages.append(next(r.message for r in caplog.records if r.levelno == logging.INFO))
        caplog.clear()

        existing_dir = tmp_path / "b"
        existing_dir.mkdir()
        (existing_dir / TOKEN_FILENAME).write_text("pre-existing-value", encoding="utf-8")
        with caplog.at_level("INFO", logger="hassette.web.auth.tokens"):
            resolve_auth_token(_make_config(), existing_dir)
        messages.append(next(r.message for r in caplog.records if r.levelno == logging.INFO))
        caplog.clear()

        with caplog.at_level("INFO", logger="hassette.web.auth.tokens"):
            resolve_auth_token(_make_config(), tmp_path / "c")
        messages.append(next(r.message for r in caplog.records if r.levelno == logging.INFO))
        caplog.clear()

        assert len(set(messages)) == 3, f"expected 3 distinct messages, got: {messages}"
