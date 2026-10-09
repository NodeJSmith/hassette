"""Which ``.env`` files an `AppConfig` reads: the running Hassette config's, unless the subclass sets ``env_file``."""

from pathlib import Path

import pytest
from pydantic_settings import SettingsConfigDict

from hassette.app.app_config import AppConfig


class InheritingConfig(AppConfig):
    greeting: str = "default"


class OptedOutConfig(AppConfig):
    model_config = SettingsConfigDict(env_file=None)

    greeting: str = "default"


@pytest.fixture
def dotenv_in_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Outside a running Hassette, the default search includes ``./.env``."""
    for key in ("HASSETTE__CONFIG_DIR", "HASSETTE_CONFIG_DIR", "GREETING"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GREETING=from-dotenv\n", encoding="utf-8")


@pytest.mark.usefixtures("dotenv_in_cwd")
def test_default_reads_the_hassette_env_files() -> None:
    assert InheritingConfig().greeting == "from-dotenv"


@pytest.mark.usefixtures("dotenv_in_cwd")
def test_env_file_none_reads_no_dotenv() -> None:
    assert OptedOutConfig().greeting == "default"
