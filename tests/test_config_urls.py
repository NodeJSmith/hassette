from hassette.config.core_config import HassetteConfig
from hassette.core.core import Hassette


def make_hassette(base_url: str) -> Hassette:
    from pydantic import SecretStr

    c = HassetteConfig.model_construct(_fields_set=set())
    # set minimal required token for properties that access it elsewhere
    c.token = SecretStr("secret-token-value")
    c.base_url = base_url
    return Hassette(c)


def test_base_url_without_scheme_uses_http_and_ws():
    h = make_hassette("localhost")
    assert h.rest_url.startswith("http://localhost:"), f"rest_url was {h.rest_url}"
    assert h.ws_url.startswith("ws://localhost:"), f"ws_url was {h.ws_url}"


def test_base_url_without_port_uses_default_8123():
    h = make_hassette("http://example.com")
    assert ":8123" in h.rest_url, f"expected :8123 in rest_url, got {h.rest_url}"
    assert ":8123" in h.ws_url, f"expected :8123 in ws_url, got {h.ws_url}"


def test_base_url_with_https_uses_wss_and_https():
    h = make_hassette("https://example.com")
    assert h.rest_url.startswith("https://"), f"rest_url was {h.rest_url}"
    assert h.ws_url.startswith("wss://"), f"ws_url was {h.ws_url}"
