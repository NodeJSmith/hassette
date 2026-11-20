"""Failure paths of ``load_app_class``."""

import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from hassette.testing import make_test_config
from hassette.utils import app_utils
from hassette.utils.app_utils import app_cache_key, load_app_class
from tests.support.helpers import write_app

NOT_A_CLASS_SOURCE = """
def not_an_app():
    return None
"""


@pytest.fixture
def app_dir(tmp_path: Path) -> Iterator[Path]:
    path = (tmp_path / "apps").resolve()
    path.mkdir()
    yield path
    sys.modules.pop("apps.function_app", None)


def test_class_name_naming_a_function_raises_not_a_subclass_and_caches_the_failure(
    tmp_path: Path, app_dir: Path
) -> None:
    module_path = write_app(app_dir, "function_app.py", NOT_A_CLASS_SOURCE)
    config = make_test_config(data_dir=tmp_path, apps={"directory": app_dir})
    cache_key = app_cache_key(module_path, "not_an_app")

    try:
        with patch.object(app_utils, "import_module", wraps=app_utils.import_module) as import_spy:
            with pytest.raises(TypeError, match="not a subclass of App or AppSync") as first:
                load_app_class(app_dir, module_path, "not_an_app", config=config)
            with pytest.raises(TypeError) as second:
                load_app_class(app_dir, module_path, "not_an_app", config=config)

        assert second.value is first.value
        assert import_spy.call_count == 1
    finally:
        app_utils.FAILED_TO_LOAD_CLASSES.pop(cache_key, None)
