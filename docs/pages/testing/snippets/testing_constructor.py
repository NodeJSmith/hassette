from pathlib import Path
from typing import Any

from hassette.app.app import App
from hassette.test_utils import AppTestHarness

AppTestHarness(
    app_cls=App,       # Your App subclass to test
    config={},         # Dict matching your app's AppConfig fields
    tmp_path=None,     # Optional: Path | None
)
