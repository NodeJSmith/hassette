"""Guard: test-suite configs always resolve ``data_dir`` to the per-process scratch data dir, never a real one."""

from pathlib import Path

import pytest

from hassette import HassetteConfig
from tests.conftest import drop_data_dir_env_vars, scratch_data_dir


@pytest.mark.parametrize("fixture_name", ["test_config", "test_config_with_apps", "test_config_with_temp_path"])
def test_config_fixture_data_dir_is_scratch_data_dir(request: pytest.FixtureRequest, fixture_name: str):
    config: HassetteConfig = request.getfixturevalue(fixture_name)

    data_dir = Path(config.data_dir).resolve()

    assert data_dir == scratch_data_dir().resolve(), (
        f"{fixture_name}.data_dir resolves to {data_dir}, not the per-process scratch data dir {scratch_data_dir()}"
    )


def test_config_class_default_data_dir_is_scratch_data_dir(test_config_class: type[HassetteConfig]):
    data_dir = Path(test_config_class().data_dir).resolve()

    assert data_dir == scratch_data_dir().resolve()


def test_drop_data_dir_env_vars_removes_every_case_variant():
    environ = {
        "HASSETTE__DATA_DIR": "/a",
        "hassette__data_dir": "/b",
        "Hassette_Data_Dir": "/c",
        "HASSETTE__CONFIG_DIR": "/keep",
        "PATH": "/usr/bin",
    }

    drop_data_dir_env_vars(environ)

    assert environ == {"HASSETTE__CONFIG_DIR": "/keep", "PATH": "/usr/bin"}
