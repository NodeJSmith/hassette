"""Tests for WebApiConfig auth fields and the CORS wildcard validator."""

import pytest
from pydantic import SecretStr, ValidationError

from hassette.config import WebApiConfig


class TestAuthFieldDefaults:
    def test_auth_enabled_defaults_true(self) -> None:
        config = WebApiConfig()
        assert config.auth_enabled is True

    def test_auth_token_defaults_none(self) -> None:
        config = WebApiConfig()
        assert config.auth_token is None

    def test_trusted_proxies_defaults_empty_tuple(self) -> None:
        config = WebApiConfig()
        assert config.trusted_proxies == ()

    def test_session_ttl_defaults_3600(self) -> None:
        config = WebApiConfig()
        assert config.session_ttl == 3600


class TestSessionTtlConstraint:
    def test_zero_session_ttl_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WebApiConfig(session_ttl=0)

    def test_negative_session_ttl_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WebApiConfig(session_ttl=-1)

    def test_positive_session_ttl_accepted(self) -> None:
        config = WebApiConfig(session_ttl=1)
        assert config.session_ttl == 1


class TestAuthTokenMasking:
    def test_auth_token_is_secret_str(self) -> None:
        config = WebApiConfig(auth_token="super-secret-token")
        assert isinstance(config.auth_token, SecretStr)

    def test_auth_token_not_in_repr(self) -> None:
        config = WebApiConfig(auth_token="super-secret-token")
        assert "super-secret-token" not in repr(config)

    def test_auth_token_not_in_str(self) -> None:
        config = WebApiConfig(auth_token="super-secret-token")
        assert "super-secret-token" not in str(config)

    def test_auth_token_unwraps_via_get_secret_value(self) -> None:
        config = WebApiConfig(auth_token="super-secret-token")
        assert config.auth_token is not None
        assert config.auth_token.get_secret_value() == "super-secret-token"


class TestCorsWildcardValidator:
    def test_wildcard_origin_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WebApiConfig(cors_origins=("*",))

    def test_wildcard_among_other_origins_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WebApiConfig(cors_origins=("http://localhost:3000", "*"))

    def test_non_wildcard_origins_accepted(self) -> None:
        config = WebApiConfig(cors_origins=("http://localhost:3000",))
        assert config.cors_origins == ("http://localhost:3000",)

    def test_default_origins_accepted(self) -> None:
        config = WebApiConfig()
        assert "*" not in config.cors_origins
