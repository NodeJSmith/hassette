from hassette import App
from hassette.test_utils import AppTestHarness

AppTestHarness(
    app_cls=App,       # Replace with your App subclass
    config={},         # Dict matching your app's AppConfig fields
    tmp_path=None,     # Optional: Path | None
)
