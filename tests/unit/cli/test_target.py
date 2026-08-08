"""Unit tests for CLI target and credential resolution (src/hassette/cli/target.py).

Pure-function tests — no HTTP client needed. Path-prefix composition is verified against a
real ``httpx2.Client`` (no transport/network involved) since that is the actual mechanism the
URL normalization behavior depends on.
"""

from pathlib import Path

import httpx2 as httpx
import pytest

from hassette.cli.target import (
    CREDENTIAL_SOURCES,
    resolve_cli_auth_token,
    resolve_server_target,
)
from hassette.exceptions import (
    CredentialResolutionError,
    ServerUrlApiSuffixError,
    ServerUrlHostRequiredError,
    ServerUrlParseError,
    ServerUrlSchemeRequiredError,
)
from hassette.web.auth.tokens import TOKEN_FILENAME
from tests.unit.cli.conftest import REMOTE_SERVER_URL, REMOTE_SERVER_URL_BARE, make_cli_config

# Target resolution precedence


class TestServerTargetPrecedence:
    def test_flag_wins_over_config_and_derived(self, tmp_path: Path) -> None:
        config = make_cli_config(
            data_dir=tmp_path, host="127.0.0.1", port=8126, cli_server_url="https://config.example.com"
        )
        target = resolve_server_target(config, server_url_flag="https://flag.example.com")
        assert target.base_url == "https://flag.example.com"

    def test_config_wins_over_derived(self, tmp_path: Path) -> None:
        config = make_cli_config(
            data_dir=tmp_path, host="127.0.0.1", port=8126, cli_server_url="https://config.example.com"
        )
        target = resolve_server_target(config)
        assert target.base_url == "https://config.example.com"

    def test_no_flag_no_config_derives_from_web_api(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, host="192.168.1.5", port=9000)
        target = resolve_server_target(config)
        assert target.base_url == "http://192.168.1.5:9000"

    def test_blank_config_server_url_falls_through_to_derived(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, host="127.0.0.1", port=8126, cli_server_url="   ")
        target = resolve_server_target(config)
        assert target.base_url == "http://127.0.0.1:8126"

    def test_derived_matches_existing_bind_all_substitution(self, tmp_path: Path) -> None:
        """The derived branch must stay byte-identical to today's f-string construction."""
        config = make_cli_config(data_dir=tmp_path, host="0.0.0.0", port=8126)
        target = resolve_server_target(config)
        assert target.base_url == "http://127.0.0.1:8126"

        config_v6 = make_cli_config(data_dir=tmp_path, host="::", port=8080)
        target_v6 = resolve_server_target(config_v6)
        assert target_v6.base_url == "http://[::1]:8080"

    def test_verify_ssl_flag_overrides_config(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_verify_ssl=True)
        target = resolve_server_target(config, verify_ssl_flag=False)
        assert target.verify_ssl is False

    def test_verify_ssl_defaults_to_config_value(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_verify_ssl=False)
        target = resolve_server_target(config)
        assert target.verify_ssl is False


# URL normalization and composition


class TestUrlNormalization:
    def test_path_prefix_composes_with_command_paths(self, tmp_path: Path) -> None:
        """The base_url, joined by httpx2, produces the expected full request URL."""
        config = make_cli_config(data_dir=tmp_path)
        target = resolve_server_target(config, server_url_flag=REMOTE_SERVER_URL)
        client = httpx.Client(base_url=target.base_url)
        request = client.build_request("GET", "/api/health")
        assert str(request.url) == "https://example.com/hassette/api/health"

    def test_ipv6_literal_round_trips_bracketed_and_is_loopback(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path)
        target = resolve_server_target(config, server_url_flag="http://[::1]:8126")
        assert target.base_url == "http://[::1]:8126"
        assert target.is_loopback is True

    def test_trailing_slash_normalized_away(self, tmp_path: Path) -> None:
        """With and without a trailing slash produce identical base URLs."""
        config = make_cli_config(data_dir=tmp_path)
        with_slash = resolve_server_target(config, server_url_flag=f"{REMOTE_SERVER_URL}/")
        without_slash = resolve_server_target(config, server_url_flag=REMOTE_SERVER_URL)
        assert with_slash.base_url == without_slash.base_url == REMOTE_SERVER_URL

    def test_query_string_and_fragment_stripped(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path)
        target = resolve_server_target(config, server_url_flag="https://example.com/hassette?x=1#frag")
        assert target.base_url == REMOTE_SERVER_URL

    def test_non_loopback_host_classified_correctly(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path)
        target = resolve_server_target(config, server_url_flag=REMOTE_SERVER_URL_BARE)
        assert target.is_loopback is False

    def test_loopback_hostname_classified_correctly(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path)
        target = resolve_server_target(config, server_url_flag="http://localhost:8126")
        assert target.is_loopback is True


# URL validation


class TestUrlValidation:
    def test_scheme_less_url_raises_naming_offending_value(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path)
        with pytest.raises(ServerUrlSchemeRequiredError) as exc_info:
            resolve_server_target(config, server_url_flag="example.com/hassette")
        assert "example.com/hassette" in str(exc_info.value)

    def test_api_suffix_url_raises_naming_corrected_form(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path)
        with pytest.raises(ServerUrlApiSuffixError) as exc_info:
            resolve_server_target(config, server_url_flag="https://hassette.example.com/hassette/api")
        message = str(exc_info.value)
        assert "https://hassette.example.com/hassette" in message
        assert "hassette.example.com/hassette/api" in message

    def test_bare_api_suffix_url_raises(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path)
        with pytest.raises(ServerUrlApiSuffixError) as exc_info:
            resolve_server_target(config, server_url_flag="https://example.com/api")
        assert REMOTE_SERVER_URL_BARE in str(exc_info.value)

    def test_api_suffix_with_trailing_slash_also_raises(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path)
        with pytest.raises(ServerUrlApiSuffixError):
            resolve_server_target(config, server_url_flag="https://example.com/hassette/api/")


# URL validation: distinct failure modes get distinct exception types


class TestUrlValidationFailureModes:
    def test_non_numeric_port_raises_parse_error(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path)
        with pytest.raises(ServerUrlParseError, match=r"host:notnum"):
            resolve_server_target(config, server_url_flag="https://host:notnum")

    def test_invalid_ipv6_brackets_raises_parse_error(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path)
        with pytest.raises(ServerUrlParseError, match=r"\[bad\]"):
            resolve_server_target(config, server_url_flag="http://[bad]")

    def test_non_http_scheme_raises_scheme_required(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path)
        with pytest.raises(ServerUrlSchemeRequiredError, match=r"ftp://host"):
            resolve_server_target(config, server_url_flag="ftp://host")

    def test_missing_host_raises_host_required(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path)
        with pytest.raises(ServerUrlHostRequiredError, match=r"https:///foo"):
            resolve_server_target(config, server_url_flag="https:///foo")


# Credential precedence chain


class TestCredentialPrecedence:
    def test_token_file_flag_overrides_all_other_sources(self, tmp_path: Path) -> None:
        flag_file = tmp_path / "flag-token"
        flag_file.write_text("flag-token", encoding="utf-8")
        config = make_cli_config(
            data_dir=tmp_path,
            cli_token_file=tmp_path / "config-token-file",
            cli_auth_token="config-auth-token",
            web_api_auth_token="web-api-token",
        )
        (tmp_path / "config-token-file").write_text("config-file-token", encoding="utf-8")
        target = resolve_server_target(config)
        result = resolve_cli_auth_token(config, target, token_file_flag=flag_file)
        assert result == "flag-token"

    def test_cli_token_file_overrides_cli_auth_token(self, tmp_path: Path) -> None:
        token_file = tmp_path / "config-token-file"
        token_file.write_text("config-file-token", encoding="utf-8")
        config = make_cli_config(data_dir=tmp_path, cli_token_file=token_file, cli_auth_token="config-auth-token")
        target = resolve_server_target(config)
        result = resolve_cli_auth_token(config, target)
        assert result == "config-file-token"

    def test_cli_auth_token_overrides_web_api_auth_token(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_auth_token="cli-token", web_api_auth_token="web-api-token")
        target = resolve_server_target(config)
        result = resolve_cli_auth_token(config, target)
        assert result == "cli-token"

    def test_web_api_auth_token_overrides_data_dir_token_file(self, tmp_path: Path) -> None:
        (tmp_path / TOKEN_FILENAME).write_text("file-token", encoding="utf-8")
        config = make_cli_config(data_dir=tmp_path, web_api_auth_token="web-api-token")
        target = resolve_server_target(config)
        result = resolve_cli_auth_token(config, target)
        assert result == "web-api-token"

    def test_data_dir_token_file_is_last_resort(self, tmp_path: Path) -> None:
        (tmp_path / TOKEN_FILENAME).write_text("file-token", encoding="utf-8")
        config = make_cli_config(data_dir=tmp_path)
        target = resolve_server_target(config)
        result = resolve_cli_auth_token(config, target)
        assert result == "file-token"

    def test_no_source_returns_none(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path)
        target = resolve_server_target(config)
        result = resolve_cli_auth_token(config, target)
        assert result is None

    def test_blank_cli_auth_token_falls_through(self, tmp_path: Path) -> None:
        (tmp_path / TOKEN_FILENAME).write_text("file-token", encoding="utf-8")
        config = make_cli_config(data_dir=tmp_path, cli_auth_token="   ")
        target = resolve_server_target(config)
        result = resolve_cli_auth_token(config, target)
        assert result == "file-token"


# Credential scope gate (loopback suppression)


class TestCredentialScopeGate:
    def test_web_api_auth_token_suppressed_for_non_loopback_target(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, web_api_auth_token="web-api-token")
        target = resolve_server_target(config, server_url_flag=REMOTE_SERVER_URL_BARE)
        result = resolve_cli_auth_token(config, target)
        assert result is None

    def test_data_dir_token_file_suppressed_for_non_loopback_target(self, tmp_path: Path) -> None:
        (tmp_path / TOKEN_FILENAME).write_text("file-token", encoding="utf-8")
        config = make_cli_config(data_dir=tmp_path)
        target = resolve_server_target(config, server_url_flag=REMOTE_SERVER_URL_BARE)
        result = resolve_cli_auth_token(config, target)
        assert result is None

    def test_cli_auth_token_sent_to_non_loopback_target(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_auth_token="cli-token")
        target = resolve_server_target(config, server_url_flag=REMOTE_SERVER_URL_BARE)
        result = resolve_cli_auth_token(config, target)
        assert result == "cli-token"

    def test_derived_lan_host_suppresses_server_scoped_sources(self, tmp_path: Path) -> None:
        """web_api.host set to a LAN address with no cli.server_url: the derived target is
        non-loopback, so the token file is suppressed. Deliberate behavior change from today.
        """
        (tmp_path / TOKEN_FILENAME).write_text("file-token", encoding="utf-8")
        config = make_cli_config(data_dir=tmp_path, host="192.168.1.5", port=8126)
        target = resolve_server_target(config)
        assert target.is_loopback is False
        result = resolve_cli_auth_token(config, target)
        assert result is None

    def test_all_credential_sources_declare_a_scope(self) -> None:
        """A source added later cannot omit the classification the gate relies on."""
        assert len(CREDENTIAL_SOURCES) > 0
        for source in CREDENTIAL_SOURCES:
            assert source.scope in ("cli", "server")


# --token-file vs cli.token_file failure modes — edge cases


class TestTokenFileFailureModes:
    def test_missing_token_file_flag_raises(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path)
        target = resolve_server_target(config)
        missing = tmp_path / "does-not-exist"
        with pytest.raises(CredentialResolutionError, match=r"does-not-exist"):
            resolve_cli_auth_token(config, target, token_file_flag=missing)

    def test_missing_cli_token_file_falls_through(self, tmp_path: Path) -> None:
        (tmp_path / TOKEN_FILENAME).write_text("file-token", encoding="utf-8")
        missing = tmp_path / "does-not-exist"
        config = make_cli_config(data_dir=tmp_path, cli_token_file=missing)
        target = resolve_server_target(config)
        result = resolve_cli_auth_token(config, target)
        assert result == "file-token"

    def test_empty_token_file_flag_treated_as_no_credential(self, tmp_path: Path) -> None:
        empty_file = tmp_path / "empty-token"
        empty_file.write_text("", encoding="utf-8")
        config = make_cli_config(data_dir=tmp_path)
        target = resolve_server_target(config)
        result = resolve_cli_auth_token(config, target, token_file_flag=empty_file)
        assert result is None


# Credential content validation


class TestCredentialHeaderSafety:
    def test_non_ascii_token_file_content_raises_naming_path(self, tmp_path: Path) -> None:
        token_file = tmp_path / "bad-token"
        token_file.write_text("café-token", encoding="utf-8")
        config = make_cli_config(data_dir=tmp_path)
        target = resolve_server_target(config)
        with pytest.raises(CredentialResolutionError, match=r"bad-token"):
            resolve_cli_auth_token(config, target, token_file_flag=token_file)

    def test_control_character_in_cli_auth_token_raises(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_auth_token="tok\x01en")
        target = resolve_server_target(config)
        with pytest.raises(CredentialResolutionError, match=r"cli\.auth_token"):
            resolve_cli_auth_token(config, target)

    def test_non_ascii_data_dir_token_file_raises_naming_path(self, tmp_path: Path) -> None:
        (tmp_path / TOKEN_FILENAME).write_text("tökén", encoding="utf-8")
        config = make_cli_config(data_dir=tmp_path)
        target = resolve_server_target(config)
        with pytest.raises(CredentialResolutionError, match=TOKEN_FILENAME.replace(".", r"\.")):
            resolve_cli_auth_token(config, target)
