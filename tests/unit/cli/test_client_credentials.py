"""Credential and auth tests for HassetteCLIClient.

Split out of ``test_client.py`` (see ``design/specs/100-decompose-oversized-test-files``) to
keep each file under the repo's 800-line threshold. Covers bearer-token attachment/precedence,
the no-literal-``--token``-argument invariant, TLS-verification flag-vs-config sourcing, and
non-loopback failure messaging.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

import hassette.cli as cli_pkg
from hassette.cli.client import CLI_AUTH_DOCS_URL, HassetteCLIClient
from hassette.cli.target import CLI_AUTH_TOKEN_ENV, CREDENTIAL_SOURCES
from hassette.config.config import HassetteConfig
from hassette.web.auth.tokens import TOKEN_FILENAME
from tests.unit.cli.conftest import REMOTE_SERVER_URL, CLIClientFactory, capture_stderr, make_cli_config
from tests.unit.cli.test_client import (
    HEALTH_ENDPOINT,
    get_expecting_exit,
    get_json_error,
    make_host_port_config,
    make_transport,
    stderr_for_connect_error,
    stderr_for_malformed_response,
    stderr_for_successful_get,
)


def unwrapped(stderr: str) -> str:
    """Collapse Rich's soft line wrapping so a phrase assertion isn't a width assertion.

    The captured stderr console has no terminal, so Rich hard-wraps at its default 80 columns.
    A message long enough to wrap would otherwise fail an ``in`` check for reasons that have
    nothing to do with the message's content.
    """
    return " ".join(stderr.split())


# Web API bearer-token credential attachment
#
# The credential-resolution tests below use the shared ``make_cli_config`` helper (see
# ``tests/unit/cli/conftest.py``), which mirrors ``test_target.py``'s cli/web_api override shape.
# ``server_url`` (and, indirectly, a non-loopback ``host``) builds a non-loopback target for
# the credential-scoping and TLS-warning tests — the default ``host="127.0.0.1"`` keeps the
# existing loopback-scoped test suite green as-is.


class TestCredentialAttachment:
    """The CLI resolves a web API bearer token and attaches it to outgoing requests."""

    # (config token, token file contents, expected Authorization header)
    #
    # The blank/empty rows are the load-bearing ones: an empty-string config token (e.g. an unset
    # env var interpolated by docker-compose as ``HASSETTE__WEB_API__AUTH_TOKEN=""``) and a
    # whitespace-only one must both be treated as unset, mirroring ``resolve_auth_token()``'s
    # server-side handling — suppressed *and* falling through to the token file, so the CLI can't
    # resolve a different credential than the service actually validates against.
    #
    # The neither-source-set case (no config token, no token file) is deliberately not a row here:
    # ``test_missing_token_never_calls_generating_resolver`` below already pins it, asserting the
    # same header absence plus the stronger invariant that the CLI never mints a token of its own.
    @pytest.mark.parametrize(
        ("config_token", "token_file", "expected_header"),
        [
            pytest.param("config-token", None, "Bearer config-token", id="config-token"),
            pytest.param(None, "file-token", "Bearer file-token", id="token-file-fallback"),
            pytest.param("config-token", "file-token", "Bearer config-token", id="config-token-beats-file"),
            pytest.param(None, "", None, id="empty-token-file"),
            pytest.param("", None, None, id="empty-config-token"),
            pytest.param("  ", "file-token", "Bearer file-token", id="blank-config-token-falls-back-to-file"),
        ],
    )
    def test_resolved_credential_attaches_expected_header(
        self,
        tmp_path: Path,
        config_token: str | None,
        token_file: str | None,
        expected_header: str | None,
    ) -> None:
        if token_file is not None:
            (tmp_path / TOKEN_FILENAME).write_text(token_file, encoding="utf-8")

        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path, web_api_auth_token=config_token))
        client, captured_headers = factory.build_capturing_headers()
        client.get(HEALTH_ENDPOINT, dict)
        assert captured_headers[0].get("authorization") == expected_header

    def test_env_var_populates_config_and_attaches_bearer_header(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The token arrives via pydantic-settings, not a hand-rolled os.environ read.

        Setting only the env var (no explicit ``web_api`` override) and confirming the
        header is attached proves ``config.web_api.auth_token`` was actually populated by
        HassetteConfig's normal settings resolution. This means, unlike its sibling tests, it
        can't use the hermetic ``make_cli_config`` factory — see "Credential tests: prefer the
        hermetic factory" in this directory's CLAUDE.md for why every ambient ``HASSETTE__*``
        var is cleared below, not just the credential-precedence ones: an ambient
        ``HASSETTE__CLI__SERVER_URL`` or ``HASSETTE__WEB_API__HOST`` pointed at a non-loopback
        target would make ``resolve_cli_auth_token()`` skip the server-scoped
        ``web_api.auth_token`` source entirely, failing this test for an unrelated reason.

        Clearing env vars isn't enough on its own — a developer's repo-root ``.env`` or
        ``hassette.toml`` could set the same problematic keys and survive the clear. This
        drops the dotenv and TOML sources entirely (keeping ``init_settings``/``env_settings``
        live) so only the real environment — the thing under test — can populate the config.
        """
        for key in list(os.environ):
            if key.upper().startswith("HASSETTE__"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("HASSETTE__WEB_API__AUTH_TOKEN", "env-token")

        class EnvOnlyConfig(HassetteConfig):
            model_config = HassetteConfig.model_config.copy() | {"toml_file": None, "env_file": None}

            @classmethod
            def settings_customise_sources(
                cls,
                _settings_cls: type[BaseSettings],
                init_settings: PydanticBaseSettingsSource,
                env_settings: PydanticBaseSettingsSource,
                dotenv_settings: PydanticBaseSettingsSource,  # noqa: ARG003 — pydantic-settings binds by keyword
                file_secret_settings: PydanticBaseSettingsSource,
            ) -> tuple[PydanticBaseSettingsSource, ...]:
                return (init_settings, env_settings, file_secret_settings)

        config = EnvOnlyConfig(token=None, data_dir=tmp_path)
        assert config.web_api.auth_token is not None
        assert config.web_api.auth_token.get_secret_value() == "env-token"

        factory = CLIClientFactory(config)
        client, captured_headers = factory.build_capturing_headers()
        client.get(HEALTH_ENDPOINT, dict)
        assert captured_headers[0]["authorization"] == "Bearer env-token"

    def test_missing_token_never_calls_generating_resolver(self, tmp_path: Path) -> None:
        """No token configured, no token file — the CLI must not mint its own token.

        A CLI-generated token would never match the running service's, so the correct
        behavior is to send the request with no credential (letting the server 401 it),
        not to silently create a value that looks like success.
        """
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path))
        client, captured_headers = factory.build_capturing_headers()
        client.get(HEALTH_ENDPOINT, dict)
        assert "authorization" not in captured_headers[0]
        assert not (tmp_path / TOKEN_FILENAME).exists()

    def test_missing_token_401_gives_clear_hint(self, tmp_path: Path) -> None:
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path))
        transport = make_transport(401, {"detail": "Unauthorized"})
        client = factory.build(transport)
        code, stderr = get_expecting_exit(client)
        assert code == 1
        assert "has hassette been started" in unwrapped(stderr)

    def test_resolved_token_401_omits_missing_token_hint(self, tmp_path: Path) -> None:
        """A wrong-but-present token is diagnosed as rejected, not as missing."""
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path, web_api_auth_token="wrong-token"))
        transport = make_transport(401, {"detail": "Invalid token"})
        client = factory.build(transport)
        _code, stderr = get_expecting_exit(client)
        assert "has hassette been started" not in unwrapped(stderr)

    def test_empty_string_config_token_401_gives_clear_hint(self, tmp_path: Path) -> None:
        """An empty-string config token must not attach a header and must not resolve as
        "present" — a resulting 401 should get the missing-token hint, not be treated as a
        plain server error from a real-but-wrong credential.
        """
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path, web_api_auth_token=""))
        transport = make_transport(401, {"detail": "Unauthorized"})
        client = factory.build(transport)
        _code, stderr = get_expecting_exit(client)
        assert "has hassette been started" in unwrapped(stderr)


# No literal --token CLI argument for the web API credential


class TestNoLiteralWebApiTokenArgument:
    def test_only_run_command_defines_a_token_flag(self) -> None:
        """The only ``--token``-shaped flag anywhere in the CLI is run.py's HA token flag.

        No literal token argument exists for the web API bearer credential — it is
        resolved exclusively from config/env/file (see ``resolve_cli_auth_token`` in
        ``hassette/cli/target.py``), never accepted as a bare CLI argument (shell-history/
        ``ps`` exposure risk).
        """
        cli_dir = Path(cli_pkg.__file__).parent
        matches: list[str] = []
        for path in cli_dir.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if '"--token"' in text or "'--token'" in text:
                matches.append(str(path.relative_to(cli_dir)))

        assert matches == [str(Path("commands") / "run.py")], (
            f"Unexpected --token flag definitions: {matches}. "
            "The web API auth token must never be a literal CLI argument."
        )


# TLS verification (--no-verify-ssl / cli.verify_ssl)


class TestVerifySslPassthrough:
    def test_verify_true_by_default(self) -> None:
        config = make_host_port_config()
        with patch("hassette.cli.client.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value = MagicMock()
            HassetteCLIClient(config, json_mode=False)
        assert mock_client_cls.call_args.kwargs["verify"] is True

    def test_verify_false_from_config(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL, cli_verify_ssl=False)
        with patch("hassette.cli.client.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value = MagicMock()
            HassetteCLIClient(config, json_mode=False)
        assert mock_client_cls.call_args.kwargs["verify"] is False


# Non-loopback targets: fail open, not fast


class TestRequestIssuedDespiteNoCredential:
    def test_non_loopback_no_credential_still_issues_request(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL)
        factory = CLIClientFactory(config)
        client, captured_headers = factory.build_capturing_headers()
        result = client.get(HEALTH_ENDPOINT, dict)
        assert result == {}
        assert len(captured_headers) == 1
        assert "authorization" not in captured_headers[0]


# Non-loopback 401: remedies split by where they apply


class TestNonLoopback401Message:
    def test_401_names_local_and_remote_remedies(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL)
        transport = make_transport(401, {"detail": "Unauthorized"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        code, stderr = get_expecting_exit(client)
        assert code == 1
        message = unwrapped(stderr)
        assert "--token-file" in message
        assert "cli.token_file" in message
        assert CLI_AUTH_TOKEN_ENV in message
        assert "trusted_proxies" in message
        assert "on the remote instance" in message
        assert "has hassette been started" not in message

    def test_401_with_resolved_credential_omits_the_suppressed_credential_hint(self, tmp_path: Path) -> None:
        """A wrong-but-present credential for a remote target is diagnosed as rejected.

        It gets neither the suppressed-credential remedy (nothing was suppressed — a CLI-scoped
        source resolved) nor the ``trusted_proxies`` one, which only applies when no credential
        is available at all. It does get the proxy caveat: a forward-auth gateway in front of a
        remote target can answer 401 itself, so the rejection cannot be pinned on Hassette.
        """
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL, cli_auth_token="wrong-token")
        transport = make_transport(401, {"detail": "Invalid token"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        _code, stderr = get_expecting_exit(client)
        message = unwrapped(stderr)
        assert "trusted_proxies" not in message
        assert "cli.auth_token" in message
        assert "the proxy may be rejecting the request" in message

    def test_loopback_401_with_resolved_credential_omits_the_proxy_caveat(self, tmp_path: Path) -> None:
        """The proxy caveat is remote-only — a loopback rejection has no gateway to blame."""
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path, cli_auth_token="wrong-token"))
        client = factory.build(make_transport(401, {"detail": "Invalid token"}))
        _code, stderr = get_expecting_exit(client)
        assert "the proxy may be rejecting the request" not in unwrapped(stderr)


# 401 messaging: name the credential source that was actually sent
#
# Content assertions run in JSON mode, where ``detail`` is the raw string the client built.
# Human mode renders the same string through Rich, which hard-wraps at the captured console's
# width and will split a long filesystem path mid-token — asserting a path against that output
# tests the console width, not the message.


class TestAuthFailureNamesCredentialSource:
    def test_401_names_the_local_token_file_that_was_attached(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The companion trap: a loopback target that is a *different* local instance.

        The CLI attaches this machine's own ``.web_api_token``; without naming it, the 401 is
        indistinguishable from a plain bad-token rejection.
        """
        token_path = tmp_path / TOKEN_FILENAME
        token_path.write_text("local-token", encoding="utf-8")
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path))
        client = factory.build(make_transport(401, {"detail": "Not authenticated"}), json_mode=True)
        detail = get_json_error(client, capsys, expect_code=1)["detail"]
        assert str(token_path) in detail
        assert "--token-file" in detail
        assert CLI_AUTH_TOKEN_ENV in detail
        assert CLI_AUTH_DOCS_URL in detail

    def test_401_names_the_cli_auth_token_source(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path, cli_auth_token="wrong-token"))
        client = factory.build(make_transport(401, {"detail": "Not authenticated"}), json_mode=True)
        detail = get_json_error(client, capsys, expect_code=1)["detail"]
        assert "cli.auth_token" in detail
        assert CLI_AUTH_DOCS_URL in detail

    def test_401_with_no_credential_says_so_and_links_the_docs(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path))
        client = factory.build(make_transport(401, {"detail": "Not authenticated"}), json_mode=True)
        detail = get_json_error(client, capsys, expect_code=1)["detail"]
        assert "no credential was attached" in detail
        # every loopback-applicable source is named, so the message can't be read as
        # "the token file is missing" while a configured web_api.auth_token sits unmentioned.
        # Derived from CREDENTIAL_SOURCES rather than spelled out, so adding or renaming a
        # source fails here instead of silently leaving the message listing a stale chain.
        for source in CREDENTIAL_SOURCES:
            assert source.name in detail
        assert TOKEN_FILENAME in detail
        assert "--token-file" in detail
        assert CLI_AUTH_TOKEN_ENV in detail
        assert CLI_AUTH_DOCS_URL in detail

    def test_401_with_unusable_configured_token_file_does_not_claim_nothing_is_configured(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A configured ``cli.token_file`` that is empty resolves to nothing, silently.

        The resolver falls through on missing/unreadable/empty content, so the client cannot
        tell "unset" from "configured but unusable". The message must therefore describe the
        resolution outcome and point at the file, not assert that no ``cli.*`` credential is
        configured — which would send the operator looking for a setting that is already there.
        """
        token_file = tmp_path / "empty-token"
        token_file.write_text("", encoding="utf-8")
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path, cli_token_file=token_file))
        client = factory.build(make_transport(401, {"detail": "Not authenticated"}), json_mode=True)
        detail = get_json_error(client, capsys, expect_code=1)["detail"]
        assert "no cli.* credential is configured" not in detail
        assert "nothing in the credential chain resolved" in detail
        assert "readable" in detail

    def test_human_mode_401_carries_the_hint_too(self, tmp_path: Path) -> None:
        """The hint is not a ``--json``-only affordance — stderr gets it as well."""
        (tmp_path / TOKEN_FILENAME).write_text("local-token", encoding="utf-8")
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path))
        client = factory.build(make_transport(401, {"detail": "Not authenticated"}))
        code, stderr = get_expecting_exit(client)
        message = unwrapped(stderr)
        assert code == 1
        assert "the credential sent came from" in message
        assert "this machine's instance" in message

    def test_401_survives_rich_markup_in_the_credential_source_path(self, tmp_path: Path) -> None:
        """A credential path containing Rich markup must not turn a 401 into a MarkupError.

        The source name is a filesystem path, and Rich reads square brackets in a printed string
        as style tags. An unescaped closing tag aborts the render, so the operator gets a
        traceback in place of the one message that would have explained the failure.
        """
        markup_dir = tmp_path / "creds["
        markup_dir.mkdir()
        token_file = markup_dir / "bold]token"
        token_file.write_text("path-token", encoding="utf-8")
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path))
        client = factory.build(make_transport(401, {"detail": "Not authenticated"}), token_file_flag=token_file)
        code, stderr = get_expecting_exit(client)
        message = unwrapped(stderr)
        assert code == 1
        assert "the credential sent came from" in message
        assert "--token-file" in message

    def test_usage_error_survives_rich_markup_in_the_token_file_path(self, tmp_path: Path) -> None:
        """An unreadable ``--token-file`` fails before any request, on a different render path.

        The 401 hint and the usage error print through the same Rich console, so a path carrying
        square brackets breaks both. Escaping only the 401 leaves the earlier failure — a path
        that cannot even be read — raising MarkupError instead of naming the path at fault.
        """
        missing = tmp_path / "creds[" / "bold]token"
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path))
        with capture_stderr() as buf, pytest.raises(SystemExit) as exc_info:
            factory.build(make_transport(200, {"status": "ok"}), token_file_flag=missing)
        message = unwrapped(buf.getvalue())
        assert exc_info.value.code == 1
        assert "--token-file could not be read" in message
        assert "bold]token" in message


# TLS-verification warning: config-sourced only, not the explicit flag


class TestVerifySslWarning:
    def test_config_sourced_insecure_warns(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL, cli_verify_ssl=False)
        stderr = stderr_for_successful_get(config)
        assert "TLS verification is disabled" in stderr

    def test_flag_sourced_insecure_does_not_warn(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL, cli_verify_ssl=False)
        stderr = stderr_for_successful_get(config, verify_ssl_flag=False, server_url_flag=None)
        assert "TLS verification is disabled" not in stderr

    def test_loopback_insecure_config_still_warns(self, tmp_path: Path) -> None:
        """The warning is about a config-vs-flag distinction, not a loopback gate — it applies
        regardless of whether the resulting target happens to be loopback.
        """
        config = make_cli_config(data_dir=tmp_path, cli_verify_ssl=False)
        stderr = stderr_for_successful_get(config)
        assert "TLS verification is disabled" in stderr

    def test_config_sourced_insecure_warns_json_mode_error_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL, cli_verify_ssl=False)
        transport = make_transport(500, {"detail": "boom"})
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        parsed = get_json_error(client, capsys)
        assert parsed["tls_verified"] is False

    def test_flag_sourced_insecure_omits_tls_verified_json_mode_error_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL, cli_verify_ssl=False)
        transport = make_transport(500, {"detail": "boom"})
        client = HassetteCLIClient(
            config, json_mode=True, transport=transport, verify_ssl_flag=False, server_url_flag=None
        )
        parsed = get_json_error(client, capsys)
        assert "tls_verified" not in parsed

    def test_config_sourced_insecure_warns_on_network_error_path(self, tmp_path: Path) -> None:
        """Mirrors the HTTP-error TLS-warning path: a connection error is a common failure
        mode, and an operator relying on ``cli.verify_ssl = false`` must be warned there too,
        not only when the failure happens to be an HTTP error response.
        """
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL, cli_verify_ssl=False)
        assert "TLS verification is disabled" in stderr_for_connect_error(config)

    def test_flag_sourced_insecure_does_not_warn_on_network_error_path(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL, cli_verify_ssl=False)
        stderr = stderr_for_connect_error(config, verify_ssl_flag=False, server_url_flag=None)
        assert "TLS verification is disabled" not in stderr

    def test_config_sourced_insecure_warns_on_malformed_response_path(self, tmp_path: Path) -> None:
        """Mirrors the HTTP-error TLS-warning path: a successful-looking response with an
        unusable body is also a common failure mode, and an operator relying on
        ``cli.verify_ssl = false`` must be warned there too.
        """
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL, cli_verify_ssl=False)
        assert "TLS verification is disabled" in stderr_for_malformed_response(config)

    def test_flag_sourced_insecure_does_not_warn_on_malformed_response_path(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL, cli_verify_ssl=False)
        stderr = stderr_for_malformed_response(config, verify_ssl_flag=False, server_url_flag=None)
        assert "TLS verification is disabled" not in stderr
