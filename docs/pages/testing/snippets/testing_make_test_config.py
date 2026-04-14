from pathlib import Path

from hassette.test_utils import make_test_config


def test_config_defaults(tmp_path: Path):
    config = make_test_config(data_dir=tmp_path)
    assert config.run_web_api is False

    # Override specific fields
    config = make_test_config(data_dir=tmp_path, base_url="http://192.168.1.100:8123")
    assert config.base_url == "http://192.168.1.100:8123"


def test_config_overrides(tmp_path: Path):
    config = make_test_config(data_dir=tmp_path, token="my-real-token", run_web_api=True)
    assert config.token == "my-real-token"
    assert config.run_web_api is True
