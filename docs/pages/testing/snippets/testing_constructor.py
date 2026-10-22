from hassette import App
from hassette.testing import AppTestHarness

AppTestHarness(
    app_cls=App,  # Replace with your App subclass
    # instance_name is required; other keys match your AppConfig fields
    config={"instance_name": "my_app"},
    tmp_path=None,  # Optional: Path | None
)
