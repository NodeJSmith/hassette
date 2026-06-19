"""Unit tests for RegistrationHandle, guard_await, ForgottenAwaitBehavior, and source_capture.

Covers:
    - un-awaited drop + gc.collect() emits HassetteForgottenAwaitWarning
    - warning message contains app identity + file:line
    - awaited handle does NOT warn; no native double-warning
    - IGNORE/WARN/ERROR behavior
    - default is WARN
    - attribution uses module-name check; source_capture uses module-name check
    - handle held alive does not warn until collected
    - gc.collect() + pytest.warns with app id + file:line
    - parametrized IGNORE/WARN/ERROR/per-app override
    - attribution from non-hassette module frame
"""

import asyncio
import contextlib
import gc
import inspect
import types
import warnings
from collections.abc import Coroutine
from enum import StrEnum
from typing import Any

import pytest

from hassette import ForgottenAwaitBehavior, HassetteForgottenAwaitWarning
from hassette.app.app_config import AppConfig
from hassette.config.config import HassetteConfig
from hassette.core.await_guard import RegistrationHandle, guard_await
from hassette.utils import source_capture as source_capture_module
from hassette.utils.source_capture import capture_registration_source, is_internal_frame


@pytest.fixture(autouse=True)
def _drain(drain_forgotten_await_handles: None) -> None:
    """Drain dropped handles after each test (shared fixture in tests/unit/conftest.py)."""


# Helpers


async def _noop_coro() -> str:
    """A trivial coroutine that returns a value."""
    return "ok"


def _make_inner_coro() -> Coroutine[Any, Any, str]:
    """Return a fresh unawaited coroutine for each test."""
    return _noop_coro()


def _make_handle(
    *,
    behavior: ForgottenAwaitBehavior = ForgottenAwaitBehavior.WARN,
    owner_identity: str = "TestApp.test_instance",
    source_location: str = "/app/my_app.py:1",
    method_name: str | None = None,
) -> RegistrationHandle[str]:
    """Construct a RegistrationHandle directly, bypassing guard_await."""
    return RegistrationHandle(
        coro=_make_inner_coro(),
        owner_identity=owner_identity,
        behavior=behavior,
        source_location=source_location,
        method_name=method_name,
    )


# drop + gc.collect() emits warning


def test_drop_unawaited_emits_warning():
    """Dropping a RegistrationHandle without awaiting emits HassetteForgottenAwaitWarning."""
    h = _make_handle(source_location="/app/my_app.py:42")
    with pytest.warns(HassetteForgottenAwaitWarning):
        del h
        gc.collect()


# warning message contains owner identity + source location


def test_warning_message_contains_app_identity():
    """Warning message contains the owning app identifier."""
    h = _make_handle(owner_identity="TestApp.my_instance", source_location="/home/user/apps/my_app.py:99")
    with pytest.warns(HassetteForgottenAwaitWarning, match="TestApp.my_instance"):
        del h
        gc.collect()


def test_warning_message_contains_source_location():
    """Warning message contains the file:line source location."""
    h = _make_handle(source_location="/home/user/apps/my_app.py:99")
    with pytest.warns(HassetteForgottenAwaitWarning, match="/home/user/apps/my_app.py:99"):
        del h
        gc.collect()


def test_warning_message_uses_public_method_name():
    """Warning names the public method the user called, not the inner private coroutine."""
    h = _make_handle(method_name="on_state_change")
    with pytest.warns(HassetteForgottenAwaitWarning, match="Coroutine from 'on_state_change' was never awaited"):
        del h
        gc.collect()


def test_warning_message_falls_back_to_inner_coro_name():
    """Without method_name, the warning falls back to the inner coroutine's __name__."""
    h = _make_handle()
    with pytest.warns(HassetteForgottenAwaitWarning, match="Coroutine from '_noop_coro' was never awaited"):
        del h
        gc.collect()


# awaited handle does NOT warn, no native double-warning


async def test_awaited_handle_does_not_warn():
    """Awaiting a handle emits no HassetteForgottenAwaitWarning."""
    h = _make_handle()
    with warnings.catch_warnings():
        warnings.simplefilter("error", HassetteForgottenAwaitWarning)
        result = await h
    assert result == "ok"
    # After await, __del__ should not warn
    del h
    gc.collect()


async def test_awaited_handle_no_native_double_warning():
    """After awaiting, no native 'coroutine was never awaited' RuntimeWarning fires."""
    h = _make_handle()
    result = await h
    assert result == "ok"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        del h
        gc.collect()
    runtime_warns = [w for w in caught if issubclass(w.category, RuntimeWarning) and "never awaited" in str(w.message)]
    assert runtime_warns == [], f"Got unexpected native warning(s): {runtime_warns}"


async def test_unawaited_no_native_double_warning():
    """Dropping un-awaited handle suppresses the inner coro's native double-warning.

    May emit a HassetteForgottenAwaitWarning (expected), but must NOT emit a raw
    RuntimeWarning about the inner coroutine being never awaited.
    """
    h = _make_handle()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        del h
        gc.collect()
    # Must NOT get the raw native RuntimeWarning (not a HassetteForgottenAwaitWarning subclass)
    native_warns = [
        w
        for w in caught
        if issubclass(w.category, RuntimeWarning)
        and not issubclass(w.category, HassetteForgottenAwaitWarning)
        and "never awaited" in str(w.message)
    ]
    assert native_warns == [], f"Got unexpected native warning(s): {native_warns}"


# all four drive/teardown entry points set _awaited = True


async def test_send_sets_awaited():
    """Driving via send() sets _awaited, suppressing the warning."""
    h = _make_handle()
    with contextlib.suppress(StopIteration):
        h.send(None)  # first send drives the coroutine
    assert h._awaited is True
    with warnings.catch_warnings():
        warnings.simplefilter("error", HassetteForgottenAwaitWarning)
        del h
        gc.collect()


def test_throw_sets_awaited():
    """Driving via throw() sets _awaited, suppressing the warning."""
    h = _make_handle()
    with contextlib.suppress(ValueError, StopIteration):
        h.throw(ValueError("test"))
    assert h._awaited is True
    with warnings.catch_warnings():
        warnings.simplefilter("error", HassetteForgottenAwaitWarning)
        del h
        gc.collect()


def test_close_sets_awaited():
    """Calling close() sets _awaited, suppressing the warning."""
    h = _make_handle()
    h.close()
    assert h._awaited is True
    with warnings.catch_warnings():
        warnings.simplefilter("error", HassetteForgottenAwaitWarning)
        del h
        gc.collect()


async def test_await_sets_awaited():
    """Using __await__ (await expr) sets _awaited."""
    h = _make_handle()
    await h
    assert h._awaited is True


# RegistrationHandle.__name__ and asyncio.iscoroutine


def test_handle_name_delegates_to_inner_coro():
    """Handle exposes __name__ from the inner coroutine."""
    h = _make_handle()
    assert h.__name__ == "_noop_coro"
    h.close()


def test_handle_satisfies_asyncio_iscoroutine():
    """asyncio.iscoroutine(handle) is True (required by run_sync path)."""
    h = _make_handle()
    assert asyncio.iscoroutine(h) is True
    h.close()


def test_handle_is_instantiable_all_abc_methods():
    """RegistrationHandle is concrete (no abstract methods raise TypeError)."""
    h = _make_handle()
    # Just instantiation proves no ABC TypeError
    assert h is not None
    h.close()


# IGNORE / WARN / ERROR / per-app override / default WARN


@pytest.mark.parametrize(
    ("behavior", "expect_warns"),
    [
        (ForgottenAwaitBehavior.WARN, True),
        (ForgottenAwaitBehavior.IGNORE, False),
    ],
)
def test_behavior_warn_and_ignore(behavior: ForgottenAwaitBehavior, expect_warns: bool):
    """WARN emits; IGNORE suppresses."""
    h = _make_handle(behavior=behavior)
    if expect_warns:
        with pytest.warns(HassetteForgottenAwaitWarning):
            del h
            gc.collect()
    else:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            del h
            gc.collect()
        hassette_warns = [w for w in caught if issubclass(w.category, HassetteForgottenAwaitWarning)]
        assert hassette_warns == []


def test_behavior_error_emits_warning():
    """ERROR behavior emits a HassetteForgottenAwaitWarning (same category as WARN)."""
    h = _make_handle(behavior=ForgottenAwaitBehavior.ERROR)
    with pytest.warns(HassetteForgottenAwaitWarning):
        del h
        gc.collect()


def test_behavior_error_with_filterwarnings_error_raises():
    """filterwarnings("error") escalates HassetteForgottenAwaitWarning to a raised exception.

    Python swallows exceptions raised inside ``__del__``, so we cannot directly observe a
    raised exception from an un-awaited ERROR handle.  Instead we verify the escalation
    mechanism: ``HassetteForgottenAwaitWarning`` issued via ``warnings.warn`` is converted to
    a raised ``HassetteForgottenAwaitWarning`` exception when
    ``filterwarnings("error", category=HassetteForgottenAwaitWarning)`` is active.  This is
    the exact call the ``ERROR`` branch in ``RegistrationHandle.__del__`` makes.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("error", category=HassetteForgottenAwaitWarning)
        with pytest.raises(HassetteForgottenAwaitWarning):
            warnings.warn("forgotten await test", HassetteForgottenAwaitWarning, stacklevel=1)


def test_default_behavior_is_warn():
    """With no explicit config, resolved behavior is WARN."""
    coro = _make_inner_coro()

    _cfg = types.SimpleNamespace(forgotten_await_behavior=None)
    _hass = types.SimpleNamespace(config=_cfg)

    class _MockOwner:
        unique_name = "TestApp.test_instance"
        app_config = types.SimpleNamespace(forgotten_await_behavior=None)
        hassette = _hass

    h = guard_await(coro, owner=_MockOwner(), source_location="/app/my_app.py:1")
    assert h._behavior == ForgottenAwaitBehavior.WARN
    h.close()


def test_per_app_override_beats_global_default():
    """Per-app forgotten_await_behavior overrides the global default."""
    coro = _make_inner_coro()

    _cfg = types.SimpleNamespace(forgotten_await_behavior=ForgottenAwaitBehavior.WARN)
    _hass = types.SimpleNamespace(config=_cfg)

    class _MockOwner:
        unique_name = "TestApp.test_instance"
        app_config = types.SimpleNamespace(forgotten_await_behavior=ForgottenAwaitBehavior.IGNORE)
        hassette = _hass

    h = guard_await(coro, owner=_MockOwner(), source_location="/app/my_app.py:1")
    assert h._behavior == ForgottenAwaitBehavior.IGNORE  # per-app wins
    h.close()


def test_global_default_used_when_per_app_none():
    """Global forgotten_await_behavior used when per-app is None."""
    coro = _make_inner_coro()

    _cfg = types.SimpleNamespace(forgotten_await_behavior=ForgottenAwaitBehavior.IGNORE)
    _hass = types.SimpleNamespace(config=_cfg)

    class _MockOwner:
        unique_name = "TestApp.test_instance"
        app_config = types.SimpleNamespace(forgotten_await_behavior=None)
        hassette = _hass

    h = guard_await(coro, owner=_MockOwner(), source_location="/app/my_app.py:1")
    assert h._behavior == ForgottenAwaitBehavior.IGNORE  # global wins when per-app is None
    h.close()


# module-name attribution


def test_source_capture_no_longer_uses_path_fragments():
    """source_capture.is_internal_frame uses module-name check, not path fragments."""
    # Old path-fragment style is removed
    assert not hasattr(source_capture_module, "INTERNAL_PATH_FRAGMENTS")


def test_source_capture_is_internal_frame_module_name():
    """is_internal_frame returns True for hassette.* modules, False for others."""
    # Simulate frame globals via SimpleNamespace
    assert is_internal_frame(types.SimpleNamespace(f_globals={"__name__": "hassette.bus.bus"})) is True
    assert is_internal_frame(types.SimpleNamespace(f_globals={"__name__": "hassette.scheduler.scheduler"})) is True
    assert is_internal_frame(types.SimpleNamespace(f_globals={"__name__": "hassette.core.await_guard"})) is True
    assert is_internal_frame(types.SimpleNamespace(f_globals={"__name__": "hassette"})) is True
    assert is_internal_frame(types.SimpleNamespace(f_globals={"__name__": "my_app"})) is False
    assert is_internal_frame(types.SimpleNamespace(f_globals={"__name__": "user.automation"})) is False
    assert is_internal_frame(types.SimpleNamespace(f_globals={"__name__": ""})) is False


def test_source_capture_skips_hassette_frames(monkeypatch):
    """capture_registration_source walks past hassette.* frames to the first user frame."""
    # Inject a fake stack: first frame is our own (skipped by [1:]),
    # next two are hassette internals, last is user code.
    fake_frames = [
        # Our own frame (skipped by [1:])
        types.SimpleNamespace(
            filename="<self>",
            lineno=0,
            frame=types.SimpleNamespace(f_globals={"__name__": "hassette.utils.source_capture"}),
        ),
        # hassette internal
        types.SimpleNamespace(
            filename="/site-packages/hassette/bus/bus.py",
            lineno=350,
            frame=types.SimpleNamespace(f_globals={"__name__": "hassette.bus.bus"}),
        ),
        # hassette internal
        types.SimpleNamespace(
            filename="/site-packages/hassette/core/await_guard.py",
            lineno=10,
            frame=types.SimpleNamespace(f_globals={"__name__": "hassette.core.await_guard"}),
        ),
        # user code (non-hassette)
        types.SimpleNamespace(
            filename="/home/user/apps/my_automation.py",
            lineno=77,
            frame=types.SimpleNamespace(f_globals={"__name__": "my_automation"}),
        ),
    ]

    monkeypatch.setattr(inspect, "stack", lambda *_args, **_kw: fake_frames)

    source_location, _ = capture_registration_source()
    # Must resolve to the user frame, not a hassette internal
    assert source_location == "/home/user/apps/my_automation.py:77"


def test_source_capture_has_limit_parameter(monkeypatch):
    """capture_registration_source respects the limit argument as a frame-count bound."""
    call_args: list = []

    original_stack = inspect.stack

    def _recording_stack(*args, **kwargs):
        call_args.append((args, kwargs))
        return original_stack(*args, **kwargs)

    monkeypatch.setattr(inspect, "stack", _recording_stack)

    # Call with limit=2 — the recording wrapper confirms context=0 was passed (cheap walk)
    result = capture_registration_source(limit=2)
    assert isinstance(result, tuple)
    assert len(result) == 2

    # The stack was called with context=0 for cheapness
    assert call_args, "inspect.stack was not called"
    _, kwargs = call_args[0]
    assert kwargs.get("context") == 0, f"Expected context=0, got {kwargs}"


def _fake_stack_frames():
    """A 4-frame fake stack: own frame, two hassette internals, then user code."""
    return [
        types.SimpleNamespace(
            filename="<self>",
            lineno=0,
            frame=types.SimpleNamespace(f_globals={"__name__": "hassette.utils.source_capture"}),
        ),
        types.SimpleNamespace(
            filename="/site-packages/hassette/bus/bus.py",
            lineno=350,
            frame=types.SimpleNamespace(f_globals={"__name__": "hassette.bus.bus"}),
        ),
        types.SimpleNamespace(
            filename="/site-packages/hassette/core/await_guard.py",
            lineno=10,
            frame=types.SimpleNamespace(f_globals={"__name__": "hassette.core.await_guard"}),
        ),
        types.SimpleNamespace(
            filename="/home/user/apps/my_automation.py",
            lineno=77,
            frame=types.SimpleNamespace(f_globals={"__name__": "my_automation"}),
        ),
    ]


def test_source_capture_limit_applied_after_skip(monkeypatch):
    """The limit bounds frames AFTER skipping our own frame, so internal frames cannot
    consume the window when the limit still has room for the user frame."""
    monkeypatch.setattr(inspect, "stack", lambda *_args, **_kw: _fake_stack_frames())

    # 3 frames remain after the own-frame skip: [bus, await_guard, user].
    # limit=3 must keep the user frame in the window (a pre-skip slice would drop it).
    source_location, _ = capture_registration_source(limit=3)
    assert source_location == "/home/user/apps/my_automation.py:77"


def test_source_capture_limit_too_small_falls_back(monkeypatch):
    """When the window is all internal frames, the documented fallback is the last frame."""
    monkeypatch.setattr(inspect, "stack", lambda *_args, **_kw: _fake_stack_frames())

    source_location, _ = capture_registration_source(limit=1)
    assert source_location == "/site-packages/hassette/bus/bus.py:350"


# handle held alive does not warn until collected


def test_handle_held_alive_does_not_warn_immediately():
    """A handle stored on an object does not warn while the object is reachable."""

    class _Holder:
        pass

    holder = _Holder()
    holder.sub = _make_handle()

    # While holder is alive, no warning yet
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gc.collect()
    hassette_warns = [w for w in caught if issubclass(w.category, HassetteForgottenAwaitWarning)]
    assert hassette_warns == [], "Should not warn while handle is reachable"

    # Now release the holder — warning fires
    with pytest.warns(HassetteForgottenAwaitWarning):
        del holder
        gc.collect()


# ForgottenAwaitBehavior enum


def test_forgotten_await_behavior_has_all_members():
    """ForgottenAwaitBehavior has IGNORE, WARN, ERROR members."""
    assert ForgottenAwaitBehavior.IGNORE is not None
    assert ForgottenAwaitBehavior.WARN is not None
    assert ForgottenAwaitBehavior.ERROR is not None


def test_forgotten_await_behavior_is_str_enum():
    """ForgottenAwaitBehavior is a StrEnum (auto() values)."""
    assert issubclass(ForgottenAwaitBehavior, StrEnum)
    # auto() produces lowercase member names
    assert ForgottenAwaitBehavior.WARN == "warn"
    assert ForgottenAwaitBehavior.IGNORE == "ignore"
    assert ForgottenAwaitBehavior.ERROR == "error"


# HassetteForgottenAwaitWarning


def test_hassette_forgotten_await_warning_is_runtime_warning():
    """HassetteForgottenAwaitWarning is a subclass of RuntimeWarning."""
    assert issubclass(HassetteForgottenAwaitWarning, RuntimeWarning)


# Config — per-app and global


def test_app_config_has_forgotten_await_behavior_field():
    """AppConfig has forgotten_await_behavior field defaulting to None."""
    config = AppConfig()
    assert hasattr(config, "forgotten_await_behavior")
    assert config.forgotten_await_behavior is None


def test_hassette_config_has_forgotten_await_behavior_field():
    """HassetteConfig has forgotten_await_behavior field defaulting to None (global default resolves to WARN)."""
    config = HassetteConfig(token="test-token")
    assert hasattr(config, "forgotten_await_behavior")
    # None means "use the hardcoded default WARN" in guard_await
    assert config.forgotten_await_behavior is None


def test_app_config_forgotten_await_behavior_accepts_enum():
    """AppConfig forgotten_await_behavior accepts ForgottenAwaitBehavior values."""
    config = AppConfig(forgotten_await_behavior=ForgottenAwaitBehavior.IGNORE)
    assert config.forgotten_await_behavior == ForgottenAwaitBehavior.IGNORE


def test_app_config_forgotten_await_behavior_accepts_string():
    """AppConfig forgotten_await_behavior coerces string values to enum."""
    config = AppConfig(forgotten_await_behavior="error")
    assert config.forgotten_await_behavior == ForgottenAwaitBehavior.ERROR
