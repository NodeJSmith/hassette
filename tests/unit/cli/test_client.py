"""Unit tests for the HassetteCLIClient HTTP client wrapper."""

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx2 as httpx
import pytest
from pydantic import BaseModel

import hassette.cli as cli_pkg
from hassette.cli.client import HassetteCLIClient
from hassette.config.config import HassetteConfig
from hassette.config.models import WebApiConfig
from hassette.test_utils.web_manifest_helpers import make_manifest_list_response, make_manifest_response
from hassette.web.auth.tokens import TOKEN_FILENAME
from hassette.web.models import AppInstanceResponse
from tests.unit.cli.conftest import REMOTE_SERVER_URL, CLIClientFactory, capture_stderr, make_cli_config

HEALTH_ENDPOINT = "/api/health"
CLI_AUTH_TOKEN_ENV = "HASSETTE__CLI__AUTH_TOKEN"

# Helpers


class SimpleModel(BaseModel):
    value: str


def make_transport(
    status_code: int = 200,
    body: Any = None,
    *,
    raise_exc: type[Exception] | None = None,
) -> httpx.MockTransport:
    """Build an httpx2.MockTransport that returns a fixed response."""
    if raise_exc is not None:

        def handler(request: httpx.Request) -> httpx.Response:
            raise raise_exc(f"mocked: {request.url}")

        return httpx.MockTransport(handler)

    json_body = json.dumps(body if body is not None else {})

    def _fixed_response(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            content=json_body.encode(),
            headers={"content-type": "application/json"},
        )

    return httpx.MockTransport(_fixed_response)


def _make_host_port_config(host: str = "127.0.0.1", port: int = 8126) -> HassetteConfig:
    """Bare host/port config for base-URL construction tests.

    Narrower than the shared ``make_cli_config()`` (from ``conftest.py``) — no ``cli``/``data_dir``
    overrides, so it can't be used for credential or target-resolution tests. Reach for
    ``make_cli_config()`` unless a test only needs to vary ``web_api.host``/``web_api.port``.
    """
    return HassetteConfig(token=None, web_api=WebApiConfig(host=host, port=port))


def _make_manifest_list(instances: list[AppInstanceResponse], app_key: str = "my_app"):
    manifest = make_manifest_response(app_key=app_key, instance_count=len(instances), instances=instances)
    return make_manifest_list_response(manifests=[manifest])


def url_capturing_client() -> tuple[HassetteCLIClient, list[str]]:
    """Build a default-target client plus the list its request URLs are recorded into."""
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        return httpx.Response(200, content=b"[]", headers={"content-type": "application/json"})

    transport = httpx.MockTransport(handler)
    return HassetteCLIClient(_make_host_port_config(), json_mode=False, transport=transport), captured_urls


def route_listeners(client: HassetteCLIClient, **kwargs: Any) -> Any:
    """Route a listener request through ``get_with_app_routing``.

    The global/per-app path pair is the same in every routing test — only ``app_key`` and
    ``instance`` are ever varied, so those stay at the call site.
    """
    return client.get_with_app_routing(
        global_path="/api/bus/listeners",
        per_app_path_template="/api/telemetry/app/{app_key}/listeners",
        model=list,
        **kwargs,
    )


def get_expecting_exit(client: HassetteCLIClient, path: str = HEALTH_ENDPOINT) -> tuple[Any, str]:
    """GET ``path`` expecting a SystemExit; return the exit code and the human-mode stderr."""
    with capture_stderr() as buf, pytest.raises(SystemExit) as exc_info:
        client.get(path, SimpleModel)
    return exc_info.value.code, buf.getvalue()


def get_json_error(
    client: HassetteCLIClient,
    capsys: pytest.CaptureFixture[str],
    path: str = HEALTH_ENDPOINT,
    *,
    expect_code: int | None = None,
) -> Any:
    """GET ``path`` on a json-mode client expecting a SystemExit; return the parsed error doc.

    Pass ``expect_code`` to also assert the exit status the client exited with.
    """
    with pytest.raises(SystemExit) as exc_info:
        client.get(path, SimpleModel)
    if expect_code is not None:
        assert exc_info.value.code == expect_code
    return json.loads(capsys.readouterr().out)


def stderr_for_successful_get(config: HassetteConfig, **client_kwargs: Any) -> str:
    """Return what a client built from ``config`` writes to stderr on a successful GET.

    The target echo and the TLS-verification warning are both success-path stderr output, so
    the response body itself never matters — only which config/flags produced the client.
    """
    client = HassetteCLIClient(
        config, json_mode=False, transport=make_transport(200, {"value": "hello"}), **client_kwargs
    )
    with capture_stderr() as buf:
        client.get(HEALTH_ENDPOINT, SimpleModel)
    return buf.getvalue()


# Base URL construction & address substitution


class TestBaseUrl:
    def test_default_address(self) -> None:
        config = _make_host_port_config("127.0.0.1", 8126)
        client = HassetteCLIClient(config, json_mode=False)
        assert client.base_url == "http://127.0.0.1:8126"

    def test_bind_all_ipv4_substituted(self) -> None:
        config = _make_host_port_config("0.0.0.0", 8126)
        client = HassetteCLIClient(config, json_mode=False)
        assert client.base_url == "http://127.0.0.1:8126"

    def test_bind_all_ipv6_substituted(self) -> None:
        config = _make_host_port_config("::", 8080)
        client = HassetteCLIClient(config, json_mode=False)
        assert client.base_url == "http://[::1]:8080"

    def test_non_default_host_port(self) -> None:
        config = _make_host_port_config("192.168.1.5", 9000)
        client = HassetteCLIClient(config, json_mode=False)
        assert client.base_url == "http://192.168.1.5:9000"


# Successful deserialization


class TestSuccessfulRequests:
    def test_returns_deserialized_pydantic_model(self) -> None:
        config = _make_host_port_config()
        transport = make_transport(200, {"value": "hello"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        result = client.get("/test", SimpleModel)
        assert isinstance(result, SimpleModel)
        assert result.value == "hello"

    def test_returns_dict_for_dict_response(self) -> None:
        config = _make_host_port_config()
        body = {"web_api": {"port": 8126}}
        transport = make_transport(200, body)
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        result = client.get("/api/config", dict)
        assert isinstance(result, dict)
        assert "web_api" in result


# tolerate_503: 503 with a valid body is deserialized, not treated as an error


class TestTolerate503:
    def test_503_deserializes_body_when_tolerated(self) -> None:
        config = _make_host_port_config()
        transport = make_transport(503, {"value": "degraded"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        result = client.get("/api/telemetry/status", SimpleModel, tolerate_503=True)
        assert isinstance(result, SimpleModel)
        assert result.value == "degraded"

    def test_503_still_exits_when_not_tolerated(self) -> None:
        config = _make_host_port_config()
        transport = make_transport(503, {"value": "degraded"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get("/api/telemetry/status", SimpleModel)
        assert exc_info.value.code == 1

    def test_500_still_exits_even_when_503_tolerated(self) -> None:
        config = _make_host_port_config()
        transport = make_transport(500, {"detail": "boom"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get("/api/telemetry/status", SimpleModel, tolerate_503=True)
        assert exc_info.value.code == 1

    def test_503_with_non_json_body_exits_instead_of_crashing(self) -> None:
        """A tolerated 503 from a proxy/LB (HTML body, not JSON) exits cleanly, not a traceback."""
        config = _make_host_port_config()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, content=b"<html>503 Service Unavailable</html>")

        client = HassetteCLIClient(config, json_mode=False, transport=httpx.MockTransport(handler))
        with pytest.raises(SystemExit) as exc_info:
            client.get("/api/telemetry/status", SimpleModel, tolerate_503=True)
        assert exc_info.value.code == 1

    def test_503_with_wrong_shape_json_exits_instead_of_crashing(self) -> None:
        """A tolerated 503 whose JSON doesn't match the model exits cleanly, not a traceback."""
        config = _make_host_port_config()
        transport = make_transport(503, {"unexpected": "shape"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get("/api/telemetry/status", SimpleModel, tolerate_503=True)
        assert exc_info.value.code == 1


# HTTP error handling (human mode)


class TestHttpErrorsHumanMode:
    def test_404_exits_with_code_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_host_port_config()
        transport = make_transport(404, {"detail": "Not found"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get("/api/missing", SimpleModel)
        assert exc_info.value.code == 1

    def test_404_prints_to_stderr(self) -> None:
        config = _make_host_port_config()
        transport = make_transport(404, {"detail": "Not found"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        _code, stderr = get_expecting_exit(client, "/api/missing")
        assert len(stderr) > 0

    def test_500_exits_with_code_1(self) -> None:
        config = _make_host_port_config()
        transport = make_transport(500, {"detail": "Internal server error"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get("/api/crash", SimpleModel)
        assert exc_info.value.code == 1

    def test_nothing_on_stdout_for_http_error_human_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_host_port_config()
        transport = make_transport(503, {"detail": "Service unavailable"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit):
            client.get(HEALTH_ENDPOINT, SimpleModel)
        captured = capsys.readouterr()
        assert captured.out == ""


# HTTP error handling (json mode)


class TestHttpErrorsJsonMode:
    def test_404_json_error_structure(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_host_port_config()
        transport = make_transport(404, {"detail": "Not found"})
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        parsed = get_json_error(client, capsys, "/api/missing", expect_code=1)
        assert parsed["error"] is True
        assert parsed["status"] == 404
        assert "detail" in parsed

    def test_json_mode_error_nothing_on_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_host_port_config()
        transport = make_transport(500, {"detail": "boom"})
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        # In json mode, error goes to stdout only
        parsed = get_json_error(client, capsys, "/api/crash")
        assert parsed["error"] is True


# Network errors (connection refused / timeout)


class TestNetworkErrors:
    def test_connection_refused_exits_code_2(self) -> None:
        config = _make_host_port_config()
        transport = make_transport(raise_exc=httpx.ConnectError)
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get(HEALTH_ENDPOINT, SimpleModel)
        assert exc_info.value.code == 2

    def test_connection_refused_mentions_address_stderr(self) -> None:
        config = _make_host_port_config("127.0.0.1", 8126)
        transport = make_transport(raise_exc=httpx.ConnectError)
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        _code, stderr = get_expecting_exit(client)
        assert "127.0.0.1" in stderr or "8126" in stderr

    def test_timeout_exits_code_2(self) -> None:
        config = _make_host_port_config()
        transport = make_transport(raise_exc=httpx.TimeoutException)
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get(HEALTH_ENDPOINT, SimpleModel)
        assert exc_info.value.code == 2

    def test_timeout_json_mode_null_status(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_host_port_config()
        transport = make_transport(raise_exc=httpx.TimeoutException)
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        parsed = get_json_error(client, capsys)
        assert parsed["error"] is True
        assert parsed["status"] is None
        assert "detail" in parsed

    def test_connection_refused_json_mode_null_status(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_host_port_config()
        transport = make_transport(raise_exc=httpx.ConnectError)
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        parsed = get_json_error(client, capsys)
        assert parsed["error"] is True
        assert parsed["status"] is None


# App-key URL routing


class TestAppKeyRouting:
    def test_no_app_uses_global_listener_url(self) -> None:
        client, captured_urls = url_capturing_client()
        route_listeners(client, app_key=None)
        assert any("/api/bus/listeners" in u for u in captured_urls)

    def test_app_key_uses_per_app_listener_url(self) -> None:
        client, captured_urls = url_capturing_client()
        route_listeners(client, app_key="my_app")
        assert any("/api/telemetry/app/my_app/listeners" in u for u in captured_urls)


# --instance flag


class TestInstanceRouting:
    def test_integer_instance_passes_index_as_query_param(self) -> None:
        client, captured_urls = url_capturing_client()
        route_listeners(client, app_key="my_app", instance="1")
        assert any("instance_index=1" in u for u in captured_urls)

    def test_name_instance_resolves_to_index(self) -> None:
        config = _make_host_port_config()
        call_count = 0
        instances = [
            AppInstanceResponse(
                app_key="my_app", index=0, instance_name="default", class_name="MyApp", status="running"
            ),
            AppInstanceResponse(
                app_key="my_app", index=1, instance_name="office", class_name="MyApp", status="running"
            ),
        ]
        manifest_list = _make_manifest_list(instances)

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if "/api/apps/manifests" in str(request.url):
                return httpx.Response(
                    200,
                    content=manifest_list.model_dump_json().encode(),
                    headers={"content-type": "application/json"},
                )
            return httpx.Response(200, content=b"[]", headers={"content-type": "application/json"})

        captured_urls: list[str] = []
        original_handler = handler

        def tracking_handler(request: httpx.Request) -> httpx.Response:
            captured_urls.append(str(request.url))
            return original_handler(request)

        client = HassetteCLIClient(config, json_mode=False, transport=httpx.MockTransport(tracking_handler))
        route_listeners(client, app_key="my_app", instance="office")
        assert any("instance_index=1" in u for u in captured_urls)

    def test_unknown_instance_name_exits_nonzero(self) -> None:
        config = _make_host_port_config()
        instances = [
            AppInstanceResponse(
                app_key="my_app", index=0, instance_name="default", class_name="MyApp", status="running"
            ),
        ]
        manifest_list = _make_manifest_list(instances)

        def handler(request: httpx.Request) -> httpx.Response:
            if "/api/apps/manifests" in str(request.url):
                return httpx.Response(
                    200,
                    content=manifest_list.model_dump_json().encode(),
                    headers={"content-type": "application/json"},
                )
            return httpx.Response(200, content=b"[]", headers={"content-type": "application/json"})

        client = HassetteCLIClient(config, json_mode=False, transport=httpx.MockTransport(handler))
        with pytest.raises(SystemExit) as exc_info:
            route_listeners(client, app_key="my_app", instance="nonexistent")
        assert exc_info.value.code != 0
        client2 = HassetteCLIClient(config, json_mode=False, transport=httpx.MockTransport(handler))
        with capture_stderr() as buf, pytest.raises(SystemExit):
            route_listeners(client2, app_key="my_app", instance="nonexistent")
        assert "default" in buf.getvalue()

    def test_instance_without_app_exits_nonzero(self) -> None:
        config = _make_host_port_config()
        transport = make_transport(200, [])
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with capture_stderr() as buf, pytest.raises(SystemExit) as exc_info:
            route_listeners(client, app_key=None, instance="office")
        assert exc_info.value.code != 0
        assert "--app" in buf.getvalue()


# --debug flag


class TestDebugMode:
    def test_debug_human_mode_shows_url_and_body(self) -> None:
        config = _make_host_port_config()
        transport = make_transport(500, {"detail": "Internal server error"})
        client = HassetteCLIClient(config, json_mode=False, debug_mode=True, transport=transport)
        _code, stderr = get_expecting_exit(client, "/api/crash")
        assert "GET" in stderr
        assert "/api/crash" in stderr
        assert "Internal server error" in stderr

    def test_debug_json_mode_includes_debug_key(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_host_port_config()
        transport = make_transport(500, {"detail": "boom"})
        client = HassetteCLIClient(config, json_mode=True, debug_mode=True, transport=transport)
        parsed = get_json_error(client, capsys, "/api/crash")
        assert parsed["error"] is True
        assert "debug" in parsed
        assert parsed["debug"]["method"] == "GET"
        assert "/api/crash" in parsed["debug"]["url"]
        assert "boom" in parsed["debug"]["body"]

    def test_no_debug_human_mode_omits_url(self) -> None:
        config = _make_host_port_config()
        transport = make_transport(500, {"detail": "Internal server error"})
        client = HassetteCLIClient(config, json_mode=False, debug_mode=False, transport=transport)
        _code, stderr = get_expecting_exit(client, "/api/crash")
        assert "URL:" not in stderr

    def test_no_debug_json_mode_omits_debug_key(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_host_port_config()
        transport = make_transport(500, {"detail": "boom"})
        client = HassetteCLIClient(config, json_mode=True, debug_mode=False, transport=transport)
        parsed = get_json_error(client, capsys, "/api/crash")
        assert "debug" not in parsed


# Web API bearer-token credential attachment
#
# The credential-resolution tests below use the shared ``make_cli_config`` helper (see
# ``tests/unit/cli/conftest.py``), which mirrors ``test_target.py``'s cli/web_api override shape.
# ``server_url`` (and, indirectly, a non-loopback ``host``) builds a non-loopback target for
# the credential-scoping and TLS-warning tests — the default ``host="127.0.0.1"`` keeps the
# existing loopback-scoped test suite green as-is.


class TestCredentialAttachment:
    """The CLI resolves a web API bearer token and attaches it to outgoing requests."""

    def test_config_auth_token_attaches_bearer_header(self, tmp_path: Path) -> None:
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path, web_api_auth_token="config-token"))
        client, captured_headers = factory.build_capturing_headers()
        client.get(HEALTH_ENDPOINT, dict)
        assert captured_headers[0]["authorization"] == "Bearer config-token"

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
            def settings_customise_sources(cls, _settings_cls, init_settings, env_settings, **kwargs):  # pyright: ignore[reportIncompatibleMethodOverride]
                return (init_settings, env_settings, kwargs["file_secret_settings"])

        config = EnvOnlyConfig(token=None, data_dir=tmp_path)
        assert config.web_api.auth_token is not None
        assert config.web_api.auth_token.get_secret_value() == "env-token"

        factory = CLIClientFactory(config)
        client, captured_headers = factory.build_capturing_headers()
        client.get(HEALTH_ENDPOINT, dict)
        assert captured_headers[0]["authorization"] == "Bearer env-token"

    def test_falls_back_to_token_file_when_config_value_absent(self, tmp_path: Path) -> None:
        (tmp_path / TOKEN_FILENAME).write_text("file-token", encoding="utf-8")
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path))
        client, captured_headers = factory.build_capturing_headers()
        client.get(HEALTH_ENDPOINT, dict)
        assert captured_headers[0]["authorization"] == "Bearer file-token"

    def test_config_value_takes_precedence_over_token_file(self, tmp_path: Path) -> None:
        (tmp_path / TOKEN_FILENAME).write_text("file-token", encoding="utf-8")
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path, web_api_auth_token="config-token"))
        client, captured_headers = factory.build_capturing_headers()
        client.get(HEALTH_ENDPOINT, dict)
        assert captured_headers[0]["authorization"] == "Bearer config-token"

    def test_no_config_value_and_no_token_file_sends_no_authorization_header(self, tmp_path: Path) -> None:
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path))
        client, captured_headers = factory.build_capturing_headers()
        client.get(HEALTH_ENDPOINT, dict)
        assert "authorization" not in captured_headers[0]

    def test_empty_token_file_treated_as_no_token(self, tmp_path: Path) -> None:
        (tmp_path / TOKEN_FILENAME).write_text("", encoding="utf-8")
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path))
        client, captured_headers = factory.build_capturing_headers()
        client.get(HEALTH_ENDPOINT, dict)
        assert "authorization" not in captured_headers[0]

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
        assert "has hassette been started" in stderr

    def test_resolved_token_401_omits_missing_token_hint(self, tmp_path: Path) -> None:
        """A wrong-but-present token gets the plain server error, not the missing-token hint."""
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path, web_api_auth_token="wrong-token"))
        transport = make_transport(401, {"detail": "Invalid token"})
        client = factory.build(transport)
        _code, stderr = get_expecting_exit(client)
        assert "has hassette been started" not in stderr

    def test_empty_string_config_token_sends_no_authorization_header(self, tmp_path: Path) -> None:
        """An empty-string config token (e.g. an unset env var interpolated by docker-compose
        as ``HASSETTE__WEB_API__AUTH_TOKEN=""``) must be treated the same as no token at all:
        no Authorization header is attached.
        """
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path, web_api_auth_token=""))
        client, captured_headers = factory.build_capturing_headers()
        client.get(HEALTH_ENDPOINT, dict)
        assert "authorization" not in captured_headers[0]

    def test_blank_config_token_falls_back_to_token_file(self, tmp_path: Path) -> None:
        """A blank configured token must mirror resolve_auth_token()'s server-side handling:
        treated as unset and falling through to the token file, not just suppressed. Otherwise
        the CLI could resolve a different (missing) credential than the service actually
        validates against, once the service falls back to a generated token for the same blank
        config value.
        """
        (tmp_path / TOKEN_FILENAME).write_text("file-token", encoding="utf-8")
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path, web_api_auth_token="  "))
        client, captured_headers = factory.build_capturing_headers()
        client.get(HEALTH_ENDPOINT, dict)
        assert captured_headers[0]["authorization"] == "Bearer file-token"

    def test_empty_string_config_token_401_gives_clear_hint(self, tmp_path: Path) -> None:
        """An empty-string config token must not attach a header and must not resolve as
        "present" — a resulting 401 should get the missing-token hint, not be treated as a
        plain server error from a real-but-wrong credential.
        """
        factory = CLIClientFactory(make_cli_config(data_dir=tmp_path, web_api_auth_token=""))
        transport = make_transport(401, {"detail": "Unauthorized"})
        client = factory.build(transport)
        _code, stderr = get_expecting_exit(client)
        assert "has hassette been started" in stderr


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
        config = _make_host_port_config()
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
        assert "--token-file" in stderr
        assert "cli.token_file" in stderr
        assert CLI_AUTH_TOKEN_ENV in stderr
        assert "trusted_proxies" in stderr
        assert "on the remote instance" in stderr
        assert "has hassette been started" not in stderr

    def test_401_with_resolved_credential_omits_the_new_hint(self, tmp_path: Path) -> None:
        """A wrong-but-present credential for a remote target gets the plain server error,
        not the suppressed-credential hint — mirrors the existing loopback equivalent.
        """
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL, cli_auth_token="wrong-token")
        transport = make_transport(401, {"detail": "Invalid token"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        _code, stderr = get_expecting_exit(client)
        assert "trusted_proxies" not in stderr


# 3xx redirect responses: likely forward-auth login page


class TestRedirectResponse:
    def test_302_mentions_redirect_forward_auth_and_docs(self) -> None:
        config = _make_host_port_config()
        transport = make_transport(302, {"detail": "Found"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        code, stderr = get_expecting_exit(client)
        assert code == 1
        assert "redirect" in stderr.lower()
        assert "forward-auth" in stderr.lower()
        assert "cli configuration docs" in stderr.lower()

    def test_302_json_mode_mentions_redirect(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_host_port_config()
        transport = make_transport(302, {"detail": "Found"})
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        parsed = get_json_error(client, capsys)
        assert "redirect" in parsed["detail"].lower()


# Full base URL (scheme + path prefix) in error messages


class TestFullBaseUrlInErrorMessages:
    def test_network_error_reports_full_base_url(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL)
        transport = make_transport(raise_exc=httpx.ConnectError)
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        _code, stderr = get_expecting_exit(client)
        assert REMOTE_SERVER_URL in stderr

    def test_http_error_reports_full_base_url(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL)
        transport = make_transport(500, {"detail": "boom"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        _code, stderr = get_expecting_exit(client)
        assert REMOTE_SERVER_URL in stderr


# Target echo: once per invocation on the success path, and unconditionally on HTTP errors


class TestTargetEcho:
    def test_non_loopback_success_shows_target(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL)
        stderr = stderr_for_successful_get(config)
        assert REMOTE_SERVER_URL in stderr

    def test_loopback_success_omits_target(self) -> None:
        config = _make_host_port_config()
        stderr = stderr_for_successful_get(config)
        assert stderr == ""

    def test_401_non_loopback_shows_target_without_debug(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL)
        transport = make_transport(401, {"detail": "Unauthorized"})
        client = HassetteCLIClient(config, json_mode=False, debug_mode=False, transport=transport)
        _code, stderr = get_expecting_exit(client)
        assert REMOTE_SERVER_URL in stderr

    def test_401_non_loopback_json_mode_includes_target(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL)
        transport = make_transport(401, {"detail": "Unauthorized"})
        client = HassetteCLIClient(config, json_mode=True, debug_mode=False, transport=transport)
        parsed = get_json_error(client, capsys)
        assert parsed["target"] == REMOTE_SERVER_URL

    def test_loopback_401_json_mode_omits_target(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_host_port_config()
        transport = make_transport(401, {"detail": "Unauthorized"})
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        parsed = get_json_error(client, capsys)
        assert "target" not in parsed


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
        transport = make_transport(raise_exc=httpx.ConnectError)
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        _code, stderr = get_expecting_exit(client)
        assert "TLS verification is disabled" in stderr

    def test_flag_sourced_insecure_does_not_warn_on_network_error_path(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL, cli_verify_ssl=False)
        transport = make_transport(raise_exc=httpx.ConnectError)
        client = HassetteCLIClient(
            config, json_mode=False, transport=transport, verify_ssl_flag=False, server_url_flag=None
        )
        _code, stderr = get_expecting_exit(client)
        assert "TLS verification is disabled" not in stderr
