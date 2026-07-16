"""Tests for HassetteConfig.timezone field validation."""

import pytest

from hassette.config import HassetteConfig
from hassette.test_utils.config import TEST_TOKEN


def make_config(**kwargs) -> HassetteConfig:
    return HassetteConfig(token=TEST_TOKEN, **kwargs)


class TestTimezoneValidation:
    def test_none_is_default(self) -> None:
        config = make_config()
        assert config.timezone is None

    def test_valid_timezone_accepted(self) -> None:
        config = make_config(timezone="America/Chicago")
        assert config.timezone == "America/Chicago"

    def test_utc_accepted(self) -> None:
        config = make_config(timezone="UTC")
        assert config.timezone == "UTC"

    def test_invalid_timezone_rejected(self) -> None:
        with pytest.raises(Exception, match="Invalid timezone"):
            make_config(timezone="Not/A/Timezone")

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(Exception, match="Invalid timezone"):
            make_config(timezone="")
