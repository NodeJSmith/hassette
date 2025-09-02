from typing import ClassVar

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings
from yarl import URL


class HassConfig(BaseSettings):
    role: ClassVar[str] = "config"

    base_url: str = Field("http://127.0.0.1:8123", description="Base URL of the Home Assistant instance")
    api_port: int = Field(8123, description="API port for Home Assistant (default is 8123 for local instances)")

    # The access token for the Home Assistant instance
    token: SecretStr = Field(
        description="Access token for Home Assistant instance",
        validation_alias=AliasChoices("token", "HASSETTE_HA_TOKEN", "HASSETTE_HASS_TOKEN", "HASSETTE_TOKEN"),
    )

    @property
    def ws_url(self) -> str:
        """Construct the WebSocket URL for Home Assistant."""
        yurl = URL(self.base_url)
        scheme = yurl.scheme if yurl.scheme else "ws"
        if "http" in scheme:
            scheme = scheme.replace("http", "ws")

        port = yurl.port if yurl.port else self.api_port
        host = yurl.host if yurl.host else self.base_url.split(":")[0]

        return str(URL.build(scheme=scheme, host=host, port=port, path="/api/websocket"))

    @property
    def rest_url(self) -> str:
        """Construct the REST API URL for Home Assistant."""
        yurl = URL(self.base_url)

        port = yurl.port if yurl.port else self.api_port
        scheme = yurl.scheme if yurl.scheme else "http"
        host = yurl.host if yurl.host else self.base_url.split(":")[0]

        return str(URL.build(scheme=scheme, host=host, port=port, path="/api/"))

    @property
    def auth_headers(self) -> dict[str, str]:
        """Return the headers required for authentication."""
        return {"Authorization": f"Bearer {self.token.get_secret_value()}"}

    @property
    def headers(self) -> dict[str, str]:
        """Return the headers for API requests."""
        headers = self.auth_headers.copy()
        headers["Content-Type"] = "application/json"
        return headers

    @property
    def truncated_token(self) -> str:
        """Return a truncated version of the token for display purposes."""
        token_value = self.token.get_secret_value()
        return f"{token_value[:6]}...{token_value[-6:]}"
