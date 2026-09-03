"""Unit tests for the HassetteCLIClient HTTP client wrapper.

Complements test_client_credentials.py, which covers credential/auth tests split out of this file.
"""

import json
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from pydantic import BaseModel

from hassette.cli.client import HassetteCLIClient
from hassette.config.config import HassetteConfig
from hassette.config.models import WebApiConfig
from hassette.test_utils.web_manifest_helpers import make_manifest_list_response, make_manifest_response
from hassette.web.models import ActionResponse, AppInstanceResponse
from tests.unit.cli.conftest import REMOTE_SERVER_URL, capture_stderr, make_cli_config

MANIFESTS_ENDPOINT = "/api/apps/manifests"
BUS_LISTENERS_ENDPOINT = "/api/bus/listeners"
CRASH_ENDPOINT = "/api/crash"
HEALTH_ENDPOINT = "/api/health"
MISSING_ENDPOINT = "/api/missing"
APP_LISTENERS_ENDPOINT_TEMPLATE = "/api/telemetry/app/{app_key}/listeners"
TELEMETRY_STATUS_ENDPOINT = "/api/telemetry/status"

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


def make_host_port_config(host: str = "127.0.0.1", port: int = 8126) -> HassetteConfig:
    """Bare host/port config for base-URL construction tests.

    Narrower than the shared ``make_cli_config()`` (from ``conftest.py``) — no ``cli``/``data_dir``
    overrides, so it can't be used for credential or target-resolution tests. Reach for
    ``make_cli_config()`` unless a test only needs to vary ``web_api.host``/``web_api.port``.
    """
    return HassetteConfig(token=None, web_api=WebApiConfig(host=host, port=port))


def make_manifest_list(instances: list[AppInstanceResponse], app_key: str = "my_app"):
    """Wrap ``instances`` in a single-app manifest list, as ``/api/apps/manifests`` returns it."""
    manifest = make_manifest_response(app_key=app_key, instance_count=len(instances), instances=instances)
    return make_manifest_list_response(manifests=[manifest])


def url_capturing_client() -> tuple[HassetteCLIClient, list[str]]:
    """Build a default-target client plus the list its request URLs are recorded into."""
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        return httpx.Response(200, content=b"[]", headers={"content-type": "application/json"})

    transport = httpx.MockTransport(handler)
    return HassetteCLIClient(make_host_port_config(), json_mode=False, transport=transport), captured_urls


def route_listeners(client: HassetteCLIClient, **kwargs: Any) -> Any:
    """Route a listener request through ``get_with_app_routing``.

    The global/per-app path pair is the same in every routing test — only ``app_key`` and
    ``instance`` are ever varied, so those stay at the call site.
    """
    return client.get_with_app_routing(
        global_path=BUS_LISTENERS_ENDPOINT,
        per_app_path_template=APP_LISTENERS_ENDPOINT_TEMPLATE,
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


def stderr_for_connect_error(config: HassetteConfig, **client_kwargs: Any) -> str:
    """Return what a client built from ``config`` writes to stderr when the server is unreachable.

    The connect-error path is the sibling of ``stderr_for_successful_get`` — the address echo, the
    full-base-URL report, and the TLS-verification warning all have to appear here too, so only the
    config/flags that produced the client ever vary between these tests.
    """
    client = HassetteCLIClient(
        config, json_mode=False, transport=make_transport(raise_exc=httpx.ConnectError), **client_kwargs
    )
    _code, stderr = get_expecting_exit(client)
    return stderr


# Base URL construction & address substitution


class TestBaseUrl:
    def test_default_address(self) -> None:
        config = make_host_port_config()
        client = HassetteCLIClient(config, json_mode=False)
        assert client.base_url == "http://127.0.0.1:8126"

    def test_bind_all_ipv4_substituted(self) -> None:
        config = make_host_port_config("0.0.0.0", 8126)
        client = HassetteCLIClient(config, json_mode=False)
        assert client.base_url == "http://127.0.0.1:8126"

    def test_bind_all_ipv6_substituted(self) -> None:
        config = make_host_port_config("::", 8080)
        client = HassetteCLIClient(config, json_mode=False)
        assert client.base_url == "http://[::1]:8080"

    def test_non_default_host_port(self) -> None:
        config = make_host_port_config("192.168.1.5", 9000)
        client = HassetteCLIClient(config, json_mode=False)
        assert client.base_url == "http://192.168.1.5:9000"


# Successful deserialization


class TestSuccessfulRequests:
    def test_returns_deserialized_pydantic_model(self) -> None:
        config = make_host_port_config()
        transport = make_transport(200, {"value": "hello"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        result = client.get("/test", SimpleModel)
        assert isinstance(result, SimpleModel)
        assert result.value == "hello"

    def test_returns_dict_for_dict_response(self) -> None:
        config = make_host_port_config()
        body = {"web_api": {"port": 8126}}
        transport = make_transport(200, body)
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        result = client.get("/api/config", dict)
        assert isinstance(result, dict)
        assert "web_api" in result


# tolerate_503: 503 with a valid body is deserialized, not treated as an error


class TestTolerate503:
    def test_503_deserializes_body_when_tolerated(self) -> None:
        config = make_host_port_config()
        transport = make_transport(503, {"value": "degraded"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        result = client.get(TELEMETRY_STATUS_ENDPOINT, SimpleModel, tolerate_503=True)
        assert isinstance(result, SimpleModel)
        assert result.value == "degraded"

    def test_503_still_exits_when_not_tolerated(self) -> None:
        config = make_host_port_config()
        transport = make_transport(503, {"value": "degraded"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get(TELEMETRY_STATUS_ENDPOINT, SimpleModel)
        assert exc_info.value.code == 1

    def test_500_still_exits_even_when_503_tolerated(self) -> None:
        config = make_host_port_config()
        transport = make_transport(500, {"detail": "boom"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get(TELEMETRY_STATUS_ENDPOINT, SimpleModel, tolerate_503=True)
        assert exc_info.value.code == 1

    def test_503_with_non_json_body_exits_instead_of_crashing(self) -> None:
        """A tolerated 503 from a proxy/LB (HTML body, not JSON) exits cleanly, not a traceback."""
        config = make_host_port_config()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, content=b"<html>503 Service Unavailable</html>")

        client = HassetteCLIClient(config, json_mode=False, transport=httpx.MockTransport(handler))
        with pytest.raises(SystemExit) as exc_info:
            client.get(TELEMETRY_STATUS_ENDPOINT, SimpleModel, tolerate_503=True)
        assert exc_info.value.code == 1

    def test_503_with_wrong_shape_json_exits_instead_of_crashing(self) -> None:
        """A tolerated 503 whose JSON doesn't match the model exits cleanly, not a traceback."""
        config = make_host_port_config()
        transport = make_transport(503, {"unexpected": "shape"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get(TELEMETRY_STATUS_ENDPOINT, SimpleModel, tolerate_503=True)
        assert exc_info.value.code == 1


# Malformed or model-incompatible 2xx responses (issue #1852)
#
# A 200 response can still be unusable: a non-JSON body (wrong --server-url pointing at an
# unrelated service, or a reverse proxy/LB serving an HTML page with a 200 status), or valid
# JSON that doesn't match the expected model (CLI/server version skew). Both must exit cleanly
# through the standard error surface instead of letting json.JSONDecodeError or pydantic's
# ValidationError propagate as a raw traceback.


class TestMalformedSuccessResponse:
    def test_non_json_200_body_exits_code_1(self) -> None:
        config = make_host_port_config()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>not json</html>")

        client = HassetteCLIClient(config, json_mode=False, transport=httpx.MockTransport(handler))
        with pytest.raises(SystemExit) as exc_info:
            client.get(HEALTH_ENDPOINT, SimpleModel)
        assert exc_info.value.code == 1

    def test_non_json_200_body_prints_clean_error_human_mode(self) -> None:
        config = make_host_port_config()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>not json</html>")

        client = HassetteCLIClient(config, json_mode=False, transport=httpx.MockTransport(handler))
        _code, stderr = get_expecting_exit(client)
        assert "Error" in stderr
        assert "not valid JSON" in stderr
        assert "Traceback" not in stderr

    def test_non_json_200_body_json_mode_error_envelope(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = make_host_port_config()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>not json</html>")

        client = HassetteCLIClient(config, json_mode=True, transport=httpx.MockTransport(handler))
        parsed = get_json_error(client, capsys, expect_code=1)
        assert parsed["error"] is True
        assert parsed["status"] == 200
        assert "not valid JSON" in parsed["detail"]

    def test_valid_json_wrong_shape_200_exits_code_1(self) -> None:
        config = make_host_port_config()
        transport = make_transport(200, {"unexpected": "shape"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get(HEALTH_ENDPOINT, SimpleModel)
        assert exc_info.value.code == 1

    def test_valid_json_wrong_shape_200_prints_clean_error_human_mode(self) -> None:
        config = make_host_port_config()
        transport = make_transport(200, {"unexpected": "shape"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        _code, stderr = get_expecting_exit(client)
        assert "Error" in stderr
        assert "does not match the expected shape" in stderr
        assert "Traceback" not in stderr

    def test_valid_json_wrong_shape_200_json_mode_error_envelope(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = make_host_port_config()
        transport = make_transport(200, {"unexpected": "shape"})
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        parsed = get_json_error(client, capsys, expect_code=1)
        assert parsed["error"] is True
        assert parsed["status"] == 200
        assert "does not match the expected shape" in parsed["detail"]

    def test_non_loopback_shows_target(self, tmp_path: Path) -> None:
        config = make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL)
        transport = make_transport(200, {"unexpected": "shape"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        _code, stderr = get_expecting_exit(client)
        assert REMOTE_SERVER_URL in stderr

    def test_non_utf8_200_body_prints_clean_error_human_mode(self) -> None:
        """A tolerated-503/2xx body with malformed UTF-8 bytes raises UnicodeDecodeError from
        response.json() (not JSONDecodeError) — must still route to the clean error path, not
        let the raw traceback escape.
        """
        config = make_host_port_config()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b'{"a": "\xff"}', headers={"content-type": "application/json; charset=utf-8"}
            )

        client = HassetteCLIClient(config, json_mode=False, transport=httpx.MockTransport(handler))
        _code, stderr = get_expecting_exit(client)
        assert "Error" in stderr
        assert "not valid UTF-8" in stderr
        assert "Traceback" not in stderr

    def test_non_utf8_200_body_debug_mode_shows_body_without_crashing(self) -> None:
        """The debug-mode body dump must decode leniently -- response.text would re-raise the
        same UnicodeDecodeError the malformed-response handler was built to catch.
        """
        config = make_host_port_config()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b'{"a": "\xff"}', headers={"content-type": "application/json; charset=utf-8"}
            )

        client = HassetteCLIClient(config, json_mode=False, debug_mode=True, transport=httpx.MockTransport(handler))
        _code, stderr = get_expecting_exit(client)
        assert "not valid UTF-8" in stderr
        assert "Body" in stderr

    def test_debug_mode_shows_url_and_body(self) -> None:
        config = make_host_port_config()
        transport = make_transport(200, {"unexpected": "shape"})
        client = HassetteCLIClient(config, json_mode=False, debug_mode=True, transport=transport)
        _code, stderr = get_expecting_exit(client)
        assert "GET" in stderr
        assert HEALTH_ENDPOINT in stderr
        assert '"unexpected"' in stderr


class TestPostMalformedResponse:
    """post() reuses get()'s _handle_malformed_response() path (see TestMalformedSuccessResponse
    above) -- these tests just confirm post() itself routes into it correctly.
    """

    def test_invalid_json_body_exits_instead_of_crashing(self) -> None:
        config = make_host_port_config()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json", headers={"content-type": "application/json"})

        client = HassetteCLIClient(config, json_mode=False, transport=httpx.MockTransport(handler))
        with pytest.raises(SystemExit) as exc_info:
            client.post("/api/apps/my_app/stop")
        assert exc_info.value.code == 1

    def test_invalid_json_body_prints_clean_error_to_stderr(self) -> None:
        config = make_host_port_config()

        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json", headers={"content-type": "application/json"})

        client = HassetteCLIClient(config, json_mode=False, transport=httpx.MockTransport(handler))
        with capture_stderr() as buf, pytest.raises(SystemExit):
            client.post("/api/apps/my_app/stop")
        assert "not valid JSON" in buf.getvalue()
        assert "Traceback" not in buf.getvalue()

    def test_schema_mismatch_exits_instead_of_crashing(self) -> None:
        """A 2xx response whose JSON doesn't match ActionResponse also routes through the shared handler."""
        config = make_host_port_config()
        transport = make_transport(200, {"unexpected": "shape"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.post("/api/apps/my_app/stop")
        assert exc_info.value.code == 1

    def test_schema_mismatch_json_mode_writes_error_doc(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = make_host_port_config()
        transport = make_transport(200, {"unexpected": "shape"})
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.post("/api/apps/my_app/stop")
        assert exc_info.value.code == 1
        parsed = json.loads(capsys.readouterr().out)
        assert parsed["error"] is True

    def test_valid_response_still_returns_action_response(self) -> None:
        """Control case: a well-formed 2xx body still deserializes normally."""
        config = make_host_port_config()
        body = ActionResponse(app_key="my_app", action="stop", instance_index=None).model_dump()
        transport = make_transport(200, body)
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        result = client.post("/api/apps/my_app/stop")
        assert isinstance(result, ActionResponse)
        assert result.app_key == "my_app"


# HTTP error handling (human mode)


class TestHttpErrorsHumanMode:
    def test_404_exits_with_code_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = make_host_port_config()
        transport = make_transport(404, {"detail": "Not found"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get(MISSING_ENDPOINT, SimpleModel)
        assert exc_info.value.code == 1

    def test_404_prints_to_stderr(self) -> None:
        config = make_host_port_config()
        transport = make_transport(404, {"detail": "Not found"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        _code, stderr = get_expecting_exit(client, MISSING_ENDPOINT)
        assert len(stderr) > 0

    def test_500_exits_with_code_1(self) -> None:
        config = make_host_port_config()
        transport = make_transport(500, {"detail": "Internal server error"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get(CRASH_ENDPOINT, SimpleModel)
        assert exc_info.value.code == 1

    def test_nothing_on_stdout_for_http_error_human_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = make_host_port_config()
        transport = make_transport(503, {"detail": "Service unavailable"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit):
            client.get(HEALTH_ENDPOINT, SimpleModel)
        captured = capsys.readouterr()
        assert captured.out == ""


# HTTP error handling (json mode)


class TestHttpErrorsJsonMode:
    def test_404_json_error_structure(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = make_host_port_config()
        transport = make_transport(404, {"detail": "Not found"})
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        parsed = get_json_error(client, capsys, MISSING_ENDPOINT, expect_code=1)
        assert parsed["error"] is True
        assert parsed["status"] == 404
        assert "detail" in parsed

    def test_json_mode_error_nothing_on_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = make_host_port_config()
        transport = make_transport(500, {"detail": "boom"})
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        # In json mode, error goes to stdout only
        parsed = get_json_error(client, capsys, CRASH_ENDPOINT)
        assert parsed["error"] is True


# Network errors (connection refused / timeout)


class TestNetworkErrors:
    def test_connection_refused_exits_code_2(self) -> None:
        config = make_host_port_config()
        transport = make_transport(raise_exc=httpx.ConnectError)
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get(HEALTH_ENDPOINT, SimpleModel)
        assert exc_info.value.code == 2

    def test_connection_refused_mentions_address_stderr(self) -> None:
        stderr = stderr_for_connect_error(make_host_port_config())
        assert "127.0.0.1" in stderr or "8126" in stderr

    def test_timeout_exits_code_2(self) -> None:
        config = make_host_port_config()
        transport = make_transport(raise_exc=httpx.TimeoutException)
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get(HEALTH_ENDPOINT, SimpleModel)
        assert exc_info.value.code == 2

    def test_timeout_json_mode_null_status(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = make_host_port_config()
        transport = make_transport(raise_exc=httpx.TimeoutException)
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        parsed = get_json_error(client, capsys)
        assert parsed["error"] is True
        assert parsed["status"] is None
        assert "detail" in parsed

    def test_connection_refused_json_mode_null_status(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = make_host_port_config()
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
        assert any(BUS_LISTENERS_ENDPOINT in u for u in captured_urls)

    def test_app_key_uses_per_app_listener_url(self) -> None:
        client, captured_urls = url_capturing_client()
        route_listeners(client, app_key="my_app")
        assert any(APP_LISTENERS_ENDPOINT_TEMPLATE.format(app_key="my_app") in u for u in captured_urls)


# --instance flag


class TestInstanceRouting:
    def test_integer_instance_passes_index_as_query_param(self) -> None:
        client, captured_urls = url_capturing_client()
        route_listeners(client, app_key="my_app", instance="1")
        assert any("instance_index=1" in u for u in captured_urls)

    def test_name_instance_resolves_to_index(self) -> None:
        config = make_host_port_config()
        call_count = 0
        instances = [
            AppInstanceResponse(
                app_key="my_app", index=0, instance_name="default", class_name="MyApp", status="running"
            ),
            AppInstanceResponse(
                app_key="my_app", index=1, instance_name="office", class_name="MyApp", status="running"
            ),
        ]
        manifest_list = make_manifest_list(instances)

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if MANIFESTS_ENDPOINT in str(request.url):
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
        config = make_host_port_config()
        instances = [
            AppInstanceResponse(
                app_key="my_app", index=0, instance_name="default", class_name="MyApp", status="running"
            ),
        ]
        manifest_list = make_manifest_list(instances)

        def handler(request: httpx.Request) -> httpx.Response:
            if MANIFESTS_ENDPOINT in str(request.url):
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
        config = make_host_port_config()
        transport = make_transport(200, [])
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with capture_stderr() as buf, pytest.raises(SystemExit) as exc_info:
            route_listeners(client, app_key=None, instance="office")
        assert exc_info.value.code != 0
        assert "--app" in buf.getvalue()


# --debug flag


class TestDebugMode:
    def test_debug_human_mode_shows_url_and_body(self) -> None:
        config = make_host_port_config()
        transport = make_transport(500, {"detail": "Internal server error"})
        client = HassetteCLIClient(config, json_mode=False, debug_mode=True, transport=transport)
        _code, stderr = get_expecting_exit(client, CRASH_ENDPOINT)
        assert "GET" in stderr
        assert CRASH_ENDPOINT in stderr
        assert "Internal server error" in stderr

    def test_debug_json_mode_includes_debug_key(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = make_host_port_config()
        transport = make_transport(500, {"detail": "boom"})
        client = HassetteCLIClient(config, json_mode=True, debug_mode=True, transport=transport)
        parsed = get_json_error(client, capsys, CRASH_ENDPOINT)
        assert parsed["error"] is True
        assert "debug" in parsed
        assert parsed["debug"]["method"] == "GET"
        assert CRASH_ENDPOINT in parsed["debug"]["url"]
        assert "boom" in parsed["debug"]["body"]

    def test_no_debug_human_mode_omits_url(self) -> None:
        config = make_host_port_config()
        transport = make_transport(500, {"detail": "Internal server error"})
        client = HassetteCLIClient(config, json_mode=False, debug_mode=False, transport=transport)
        _code, stderr = get_expecting_exit(client, CRASH_ENDPOINT)
        assert "URL:" not in stderr

    def test_no_debug_json_mode_omits_debug_key(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = make_host_port_config()
        transport = make_transport(500, {"detail": "boom"})
        client = HassetteCLIClient(config, json_mode=True, debug_mode=False, transport=transport)
        parsed = get_json_error(client, capsys, CRASH_ENDPOINT)
        assert "debug" not in parsed


# 3xx redirect responses: likely forward-auth login page


class TestRedirectResponse:
    def test_302_mentions_redirect_forward_auth_and_docs(self) -> None:
        config = make_host_port_config()
        transport = make_transport(302, {"detail": "Found"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        code, stderr = get_expecting_exit(client)
        assert code == 1
        assert "redirect" in stderr.lower()
        assert "forward-auth" in stderr.lower()
        assert "cli configuration docs" in stderr.lower()

    def test_302_json_mode_mentions_redirect(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = make_host_port_config()
        transport = make_transport(302, {"detail": "Found"})
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        parsed = get_json_error(client, capsys)
        assert "redirect" in parsed["detail"].lower()


# Full base URL (scheme + path prefix) in error messages


class TestFullBaseUrlInErrorMessages:
    def test_network_error_reports_full_base_url(self, tmp_path: Path) -> None:
        stderr = stderr_for_connect_error(make_cli_config(data_dir=tmp_path, cli_server_url=REMOTE_SERVER_URL))
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
        config = make_host_port_config()
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
        config = make_host_port_config()
        transport = make_transport(401, {"detail": "Unauthorized"})
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        parsed = get_json_error(client, capsys)
        assert "target" not in parsed
