"""Degraded App Demo.

Multi-instance demo app used to reproduce `ManifestStatus.DEGRADED` for documentation
screenshots. One instance starts normally; the other is configured to crash during
`on_initialize()`. `AppRegistry.build_manifest_info()` computes "degraded" whenever an app has
both a running instance and a failed one — this app exists solely to put it in that state on
demand.

NOT a real automation — this exists solely to populate the UI with a representative "degraded"
app for screenshots. `autostart = false` in hassette.toml: it does nothing useful running
continuously, so it's started via the API only when a degraded-status screenshot is needed.
"""

from pydantic_settings import SettingsConfigDict

from hassette import App, AppConfig


class DegradedDemoConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="degraded_demo_")

    crash_on_init: bool = False


class DegradedDemo(App[DegradedDemoConfig]):
    """One instance runs normally; the other crashes on init to produce a degraded manifest status."""

    async def on_initialize(self) -> None:
        if self.app_config.crash_on_init:
            raise RuntimeError("degraded_demo: deliberate crash for degraded-status screenshots")
        self.logger.info("degraded_demo instance %s running normally", self.app_config.instance_name)
