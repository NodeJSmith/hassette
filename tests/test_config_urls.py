from hassette.config.core_config import HassetteConfig


def make_config(base_url: str) -> HassetteConfig:
    from pydantic import SecretStr

    c = HassetteConfig.model_construct(_fields_set=set())
    # set minimal required token for properties that access it elsewhere
    c.token = SecretStr("secret-token-value")
    c.base_url = base_url
    return c


def test_base_url_without_scheme_uses_http_and_ws():
    c = make_config("localhost")
    assert c.rest_url.startswith("http://localhost:"), f"rest_url was {c.rest_url}"
    assert c.ws_url.startswith("ws://localhost:"), f"ws_url was {c.ws_url}"


def test_base_url_without_port_uses_default_8123():
    c = make_config("http://example.com")
    assert ":8123" in c.rest_url, f"expected :8123 in rest_url, got {c.rest_url}"
    assert ":8123" in c.ws_url, f"expected :8123 in ws_url, got {c.ws_url}"


def test_base_url_with_https_uses_wss_and_https():
    c = make_config("https://example.com")
    assert c.rest_url.startswith("https://"), f"rest_url was {c.rest_url}"
    assert c.ws_url.startswith("wss://"), f"ws_url was {c.ws_url}"
