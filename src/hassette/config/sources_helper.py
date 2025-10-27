import logging
from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic_settings.sources import InitSettingsSource, PathType, TomlConfigSettingsSource

DEFAULT_PATH = Path()
DEFAULT_HASSETTE_TOML_PATH = Path("hassette.toml")


LOGGER = logging.getLogger(__name__)


class HassetteTomlConfigSettingsSource(TomlConfigSettingsSource):
    def __init__(self, settings_cls: type[BaseSettings], toml_file: PathType | None = DEFAULT_PATH):
        self.toml_file_path = toml_file if toml_file != DEFAULT_PATH else settings_cls.model_config.get("toml_file")
        self.toml_data = self._read_files(self.toml_file_path)

        if "hassette" not in self.toml_data:
            # just let the standard class handle it
            super().__init__(settings_cls, self.toml_file_path)
            return

        LOGGER.info("Merging 'hassette' section from TOML config into top level")
        top_level_keys = set(self.toml_data.keys()) - {"hassette"}
        hassette_values = self.toml_data.pop("hassette")
        for key in top_level_keys.intersection(hassette_values.keys()):
            LOGGER.warning(
                "Key %r found in both top level and 'hassette' section of TOML config, "
                "the [hassette] value will be used",
                key,
            )

        self.toml_data.update(hassette_values)

        # need to call InitSettingSource directly, as super() expects a file path
        # as the second argument
        InitSettingsSource.__init__(self, settings_cls, self.toml_data)
