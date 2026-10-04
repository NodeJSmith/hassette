"""Guard: test-suite configs never resolve ``data_dir`` to the developer's real hassette data dir."""

from pathlib import Path

import platformdirs
import pytest

from hassette import HassetteConfig

PLATFORM_DATA_DIR = platformdirs.user_data_path("hassette").resolve()


@pytest.mark.parametrize("fixture_name", ["test_config", "test_config_with_apps", "test_config_with_temp_path"])
def test_config_fixture_data_dir_is_outside_platform_data_dir(request: pytest.FixtureRequest, fixture_name: str):
    config: HassetteConfig = request.getfixturevalue(fixture_name)

    data_dir = Path(config.data_dir).resolve()

    assert not data_dir.is_relative_to(PLATFORM_DATA_DIR), (
        f"{fixture_name}.data_dir resolves to {data_dir}, inside the platform user data dir {PLATFORM_DATA_DIR}"
    )


def test_config_class_default_data_dir_is_outside_platform_data_dir(test_config_class: type[HassetteConfig]):
    data_dir = Path(test_config_class().data_dir).resolve()

    assert not data_dir.is_relative_to(PLATFORM_DATA_DIR)
