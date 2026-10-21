"""AppConfig's own fields are read by name, whatever alias generator a subclass sets."""

from pydantic.alias_generators import to_camel
from pydantic_settings import SettingsConfigDict

from hassette import AppConfig


class CamelCaseConfig(AppConfig):
    model_config = SettingsConfigDict(alias_generator=to_camel)

    off_delay: int = 30


def test_framework_fields_are_read_by_name_under_an_alias_generator() -> None:
    """Config loading writes instance_name by name; an alias generator must not drop it into extras."""
    config = CamelCaseConfig.model_validate({"instance_name": "upstairs", "log_level": "DEBUG", "offDelay": 5})

    assert config.instance_name == "upstairs"
    assert config.log_level == "DEBUG"
    assert config.off_delay == 5


def test_user_fields_still_follow_the_alias_generator() -> None:
    """Only the framework's fields get the by-name lookup; a user field is read only by its alias."""
    config = CamelCaseConfig.model_validate({"instance_name": "upstairs", "off_delay": 5})

    assert config.off_delay == 30
