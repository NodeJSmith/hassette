"""Reload-all through the real lifecycle, loader and config on app files a test edits (spec 162).

Like ``test_hot_reload``, watcher cases emit the file-watcher event directly instead of running the watcher.
"""

import asyncio
import logging
import os
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from hassette_wire import ResourceStatus

import hassette.core.app_lifecycle_changes as app_lifecycle_changes
from hassette.config.classes import AppManifest
from hassette.exceptions import ReloadBusyError, ReloadConfigInvalidError, ReloadSyntaxError
from hassette.schemas.app_outcomes import OutcomeResult
from hassette.testing import HassetteHarness, wait_for
from tests.support.harness import preserve_config
from tests.support.helpers import create_app_manifest, emit_change_and_wait_for_app_status, write_app, write_app_toml

if TYPE_CHECKING:
    from hassette.app.app import App
    from hassette.app.app_config import AppConfig
    from hassette.core.app_handler import AppHandler

APP_SOURCE = """
from hassette import App
from {helper} import VALUE


class {class_name}(App):
    pass
"""


@pytest.fixture
def harness(hassette_with_app_handler_custom_config: HassetteHarness) -> Iterator[HassetteHarness]:
    """The harness, with its config restored and its temp app dir emptied after each test."""
    app_dir = hassette_with_app_handler_custom_config.config.apps.directory
    with preserve_config(hassette_with_app_handler_custom_config.config):
        yield hassette_with_app_handler_custom_config
    for path in app_dir.iterdir():
        if path.is_file():
            path.unlink()
        elif path.is_dir() and path.name == "__pycache__":
            shutil.rmtree(path)


def module_value(app: "App[AppConfig]") -> int:
    """The ``VALUE`` the app's module imported from its helper."""
    return sys.modules[type(app).__module__].VALUE


class ReloadAllTestBase:
    """Shared setup: the harness, its app dir and TOML, and a helper module every deployed app imports."""

    harness: HassetteHarness
    app_handler: "AppHandler"
    app_dir: Path
    toml_file: Path
    helper: str

    @pytest.fixture(autouse=True)
    def setup(self, harness: HassetteHarness) -> None:
        self.harness = harness
        self.app_handler = harness.app_handler
        self.app_dir = harness.config.apps.directory
        self.toml_file = next(iter(harness.config.toml_files))
        # A unique bare module name, so no test imports a helper another test loaded.
        self.helper = f"helper_{os.urandom(4).hex()}"

    def write_helper(self, source: str) -> Path:
        return write_app(self.app_dir, f"{self.helper}.py", source)

    async def deploy(self, *suffixes: str, status: ResourceStatus = ResourceStatus.RUNNING) -> list[AppManifest]:
        """Write each app (importing the helper) and the TOML, announce them, and wait for ``status``."""
        manifests = [create_app_manifest(suffix=suffix, app_dir=self.app_dir) for suffix in suffixes]
        for manifest in manifests:
            write_app(
                self.app_dir,
                manifest.filename,
                APP_SOURCE.format(helper=self.helper, class_name=manifest.class_name),
            )
        write_app_toml(self.toml_file, app_dir=self.app_dir, apps=manifests)
        await emit_change_and_wait_for_app_status(
            self.harness.hassette,
            {self.toml_file, *(manifest.full_path for manifest in manifests)},
            *(manifest.app_key for manifest in manifests),
            status=status,
        )
        return manifests

    def running(self, app_key: str) -> "App[AppConfig]":
        app = self.app_handler.registry.get(app_key)
        assert app is not None, f"expected {app_key} to be running"
        return app


class TestManualReloadAll(ReloadAllTestBase):
    async def test_a_helper_edit_reaches_every_app(self) -> None:
        self.write_helper("VALUE = 1\n")
        first, second = await self.deploy("rafirst", "rasecond")
        self.write_helper("VALUE = 2\n")

        result = await self.app_handler.reload_all()

        assert module_value(self.running(first.app_key)) == 2
        assert module_value(self.running(second.app_key)) == 2
        assert set(result.apps) == {first.app_key, second.app_key}
        assert result.count(OutcomeResult.SUCCEEDED) == 2

    async def test_a_syntax_error_refuses_before_anything_stops(self) -> None:
        self.write_helper("VALUE = 1\n")
        (manifest,) = await self.deploy("rasyntax")
        before = self.running(manifest.app_key)
        self.write_helper("VALUE = 1\ndef broken(:\n")

        with pytest.raises(ReloadSyntaxError, match=rf"^{self.helper}\.py:2: "):
            await self.app_handler.reload_all()

        assert self.running(manifest.app_key) is before

    async def test_an_invalid_config_refuses_before_anything_stops(self) -> None:
        self.write_helper("VALUE = 1\n")
        (manifest,) = await self.deploy("rainvalid")
        before = self.running(manifest.app_key)
        self.toml_file.write_text("[hassette\nnot toml")

        with pytest.raises(ReloadConfigInvalidError):
            await self.app_handler.reload_all()

        assert self.running(manifest.app_key) is before

    async def test_an_app_that_failed_on_the_old_helper_recovers(self) -> None:
        self.write_helper("OTHER = 1\n")  # no VALUE: the app's import fails
        (manifest,) = await self.deploy("rafailed", status=ResourceStatus.FAILED)
        assert manifest.app_key in self.app_handler.registry.tracked_app_keys()
        self.write_helper("VALUE = 3\n")

        result = await self.app_handler.reload_all()

        assert module_value(self.running(manifest.app_key)) == 3
        assert result.count(OutcomeResult.SUCCEEDED) == 1

    async def test_a_stopped_app_stays_stopped_and_starts_on_the_new_code(self) -> None:
        self.write_helper("VALUE = 1\n")
        kept, stopped = await self.deploy("rakept", "rastopped")
        await self.app_handler.stop_app(stopped.app_key)
        self.write_helper("VALUE = 4\n")

        result = await self.app_handler.reload_all()

        assert stopped.app_key not in result.apps
        assert self.app_handler.registry.get(stopped.app_key) is None
        assert module_value(self.running(kept.app_key)) == 4
        await self.app_handler.start_app(stopped.app_key)
        assert module_value(self.running(stopped.app_key)) == 4

    async def test_a_busy_reload_refuses_without_waiting(self) -> None:
        self.write_helper("VALUE = 1\n")
        (manifest,) = await self.deploy("rabusy")
        before = self.running(manifest.app_key)
        lock = self.app_handler.lifecycle._reconcile_lock
        await lock.acquire()
        try:
            with pytest.raises(ReloadBusyError) as info:
                await asyncio.wait_for(self.app_handler.reload_all(), timeout=1)
            assert str(info.value) == "Another reload is still running"
        finally:
            lock.release()
        assert self.running(manifest.app_key) is before

    async def test_a_busy_app_refuses_naming_it(self) -> None:
        """The refusal comes before the config is adopted, so an edit on disk leaves the config and registry as is."""
        self.write_helper("VALUE = 1\n")
        (manifest,) = await self.deploy("rabusykey")
        added = create_app_manifest(suffix="rabusyadd", app_dir=self.app_dir)
        write_app(self.app_dir, added.filename, APP_SOURCE.format(helper=self.helper, class_name=added.class_name))
        write_app_toml(self.toml_file, app_dir=self.app_dir, apps=[manifest, added])
        lock = self.app_handler.lifecycle._get_app_key_lock(manifest.app_key)
        await lock.acquire()
        try:
            with pytest.raises(ReloadBusyError) as info:
                await self.app_handler.reload_all()
        finally:
            lock.release()

        assert repr(manifest.app_key) in str(info.value)
        assert not self.app_handler.lifecycle._reconcile_lock.busy
        assert set(self.harness.config.apps.manifests) == {manifest.app_key}
        assert set(self.app_handler.registry.manifests) == {manifest.app_key}

    async def test_apps_stop_before_the_eviction_and_start_after_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Evicting while an old instance still ran would let its teardown import the new code (spec 162 D12)."""
        self.write_helper("VALUE = 1\n")
        (manifest,) = await self.deploy("raorder")
        self.write_helper("VALUE = 8\n")
        at_eviction: list[object] = []
        evict = app_lifecycle_changes.evict_apps_package

        def recording_evict(roots: frozenset[Path]) -> list[str]:
            at_eviction.append(self.app_handler.registry.get(manifest.app_key))
            return evict(roots)

        monkeypatch.setattr(app_lifecycle_changes, "evict_apps_package", recording_evict)

        await self.app_handler.reload_all()

        assert at_eviction == [None]
        assert module_value(self.running(manifest.app_key)) == 8

    async def test_a_failed_eviction_still_restarts_the_apps(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        self.write_helper("VALUE = 1\n")
        (manifest,) = await self.deploy("raevictfail")
        before = self.running(manifest.app_key)

        def failing_evict(_roots: frozenset[Path]) -> list[str]:
            raise RuntimeError("eviction broke")

        monkeypatch.setattr(app_lifecycle_changes, "evict_apps_package", failing_evict)

        with caplog.at_level(logging.ERROR):
            result = await self.app_handler.reload_all()

        assert self.running(manifest.app_key) is not before
        assert result.count(OutcomeResult.SUCCEEDED) == 1
        assert any("Evicting the app-code modules failed" in record.message for record in caplog.records)

    async def test_modules_under_an_app_dir_the_edit_removed_are_evicted(self) -> None:
        self.write_helper("VALUE = 1\n")
        (kept,) = await self.deploy("radirkeep")
        other_dir = self.app_dir.parent / f"other_apps_{os.urandom(4).hex()}"
        other_helper = f"helper_{os.urandom(4).hex()}"
        try:
            write_app(other_dir, f"{other_helper}.py", "VALUE = 1\n")
            away = create_app_manifest(suffix="radiraway", app_dir=other_dir)
            write_app(other_dir, away.filename, APP_SOURCE.format(helper=other_helper, class_name=away.class_name))
            write_app_toml(self.toml_file, app_dir=self.app_dir, apps=[kept, away])
            await emit_change_and_wait_for_app_status(
                self.harness.hassette, {self.toml_file, away.full_path}, away.app_key
            )
            assert other_helper in sys.modules

            write_app_toml(self.toml_file, app_dir=self.app_dir, apps=[kept])
            result = await self.app_handler.reload_all()

            assert result.apps[away.app_key].action == "stop"
            assert other_helper not in sys.modules
        finally:
            shutil.rmtree(other_dir, ignore_errors=True)

    async def test_the_config_is_reread_removed_apps_stop_and_added_ones_start(self) -> None:
        self.write_helper("VALUE = 1\n")
        kept, removed = await self.deploy("rakeep", "raremove")
        added = create_app_manifest(suffix="raadd", app_dir=self.app_dir)
        write_app(self.app_dir, added.filename, APP_SOURCE.format(helper=self.helper, class_name=added.class_name))
        write_app_toml(self.toml_file, app_dir=self.app_dir, apps=[kept, added])

        result = await self.app_handler.reload_all()

        assert {key: app.action for key, app in result.apps.items()} == {
            kept.app_key: "reload",
            removed.app_key: "stop",
            added.app_key: "start",
        }
        assert self.app_handler.registry.get(removed.app_key) is None
        assert self.running(added.app_key) is not None
        assert result.count(OutcomeResult.FAILED) == 0

    async def test_a_waiting_reload_runs_after_the_busy_one(self) -> None:
        self.write_helper("VALUE = 1\n")
        (manifest,) = await self.deploy("rawait")
        self.write_helper("VALUE = 5\n")
        lock = self.app_handler.lifecycle._reconcile_lock
        await lock.acquire()
        task = asyncio.create_task(self.app_handler.reload_all(wait=True))
        try:
            # The reload counts as a claim on the lock once it is waiting for it, alongside this test's hold.
            await wait_for(lambda: lock.claims == 2, desc="the reload waiting for the reconcile lock")
            assert not task.done()
        finally:
            lock.release()

        await asyncio.wait_for(task, timeout=10)

        assert module_value(self.running(manifest.app_key)) == 5


class TestWatcherReloadAll(ReloadAllTestBase):
    """The file watcher's half: a helper edit reloads every app; a syntax error reloads none of them."""

    async def test_a_helper_edit_reloads_every_app_once(self, caplog: pytest.LogCaptureFixture) -> None:
        self.write_helper("VALUE = 1\n")
        first, second = await self.deploy("rawfirst", "rawsecond")
        helper = self.write_helper("VALUE = 6\n")

        with caplog.at_level(logging.INFO):
            await emit_change_and_wait_for_app_status(
                self.harness.hassette, {helper, first.full_path}, first.app_key, second.app_key
            )
            await wait_for(
                lambda: any("File-watcher reload-all finished" in record.message for record in caplog.records),
                timeout=10,
                desc="the reload-all summary line",
            )

        assert module_value(self.running(first.app_key)) == 6
        assert module_value(self.running(second.app_key)) == 6
        finished = [record for record in caplog.records if "File-watcher reload-all finished" in record.message]
        assert len(finished) == 1

    async def test_one_event_with_several_helpers_reloads_once(self, caplog: pytest.LogCaptureFixture) -> None:
        """The watcher batches a burst of saves into one event (watchfiles' debounce); that event reloads once."""
        self.write_helper("VALUE = 1\n")
        (manifest,) = await self.deploy("rawburst")
        helper = self.write_helper("VALUE = 9\n")
        other = write_app(self.app_dir, f"other_{self.helper}.py", "OTHER = 1\n")

        with caplog.at_level(logging.INFO):
            await emit_change_and_wait_for_app_status(self.harness.hassette, {helper, other}, manifest.app_key)
            await wait_for(
                lambda: any("File-watcher reload-all finished" in record.message for record in caplog.records),
                timeout=10,
                desc="the reload-all summary line",
            )

        assert module_value(self.running(manifest.app_key)) == 9
        finished = [record for record in caplog.records if "File-watcher reload-all finished" in record.message]
        assert len(finished) == 1

    async def test_a_helper_syntax_error_restarts_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        self.write_helper("VALUE = 1\n")
        (manifest,) = await self.deploy("rawsyntax")
        before = self.running(manifest.app_key)
        helper = self.write_helper("def broken(:\n")

        with caplog.at_level(logging.ERROR):
            await self.app_handler.lifecycle.handle_change_event(frozenset({helper}))

        assert self.running(manifest.app_key) is before
        assert any(f"{self.helper}.py:1:" in record.message for record in caplog.records)

    async def test_an_invalid_config_skips_the_reload_all(self) -> None:
        self.write_helper("VALUE = 1\n")
        (manifest,) = await self.deploy("rawinvalid")
        before = self.running(manifest.app_key)
        helper = self.write_helper("VALUE = 7\n")
        self.toml_file.write_text("[hassette\nnot toml")

        await self.app_handler.lifecycle.handle_change_event(frozenset({helper, self.toml_file}))

        assert self.running(manifest.app_key) is before

    async def test_a_syntax_error_drops_only_the_reload_all(self) -> None:
        """The changed app file is still reimported, on the helper module already loaded."""
        self.write_helper("VALUE = 1\n")
        (manifest,) = await self.deploy("rawpartial")
        before = self.running(manifest.app_key)
        helper = self.write_helper("def broken(:\n")

        await self.app_handler.lifecycle.handle_change_event(frozenset({helper, manifest.full_path}))

        after = self.running(manifest.app_key)
        assert after is not before
        assert module_value(after) == 1
