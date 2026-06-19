"""Unit tests for BlockingIOBehavior, HassetteBlockingIOWarning, BlockingIODetectionConfig,
and resolve_blocking_io_behavior.

Covers:
    - per-app value wins over global; global wins over hardcoded default; default is WARN
    - per-app blocking_io_behavior overrides global; 'ignore' resolves to IGNORE
"""

import types
import warnings
from enum import StrEnum
from pathlib import Path

import pytest

from hassette.app.app_config import AppConfig
from hassette.config.models import BlockingIODetectionConfig
from hassette.core.block_io_guard import DEFAULT_BLOCKING_IO_BEHAVIOR, resolve_blocking_io_behavior
from hassette.exceptions import HassetteBlockingIOWarning
from hassette.test_utils import make_test_config
from hassette.types.enums import BlockingIOBehavior


def test_blocking_io_behavior_has_all_members() -> None:
    """BlockingIOBehavior has exactly the IGNORE, WARN, ERROR members."""
    assert {m.name for m in BlockingIOBehavior} == {"IGNORE", "WARN", "ERROR"}
    assert {m.value for m in BlockingIOBehavior} == {"ignore", "warn", "error"}


def test_blocking_io_behavior_is_str_enum() -> None:
    """BlockingIOBehavior is a StrEnum with lowercased auto() values."""
    assert issubclass(BlockingIOBehavior, StrEnum)
    assert BlockingIOBehavior.WARN == "warn"
    assert BlockingIOBehavior.IGNORE == "ignore"
    assert BlockingIOBehavior.ERROR == "error"


def test_blocking_io_behavior_parse_ignore() -> None:
    """BlockingIOBehavior('ignore') parses to IGNORE."""
    assert BlockingIOBehavior("ignore") is BlockingIOBehavior.IGNORE


def test_blocking_io_behavior_parse_warn() -> None:
    """BlockingIOBehavior('warn') parses to WARN."""
    assert BlockingIOBehavior("warn") is BlockingIOBehavior.WARN


def test_blocking_io_behavior_parse_error() -> None:
    """BlockingIOBehavior('error') parses to ERROR."""
    assert BlockingIOBehavior("error") is BlockingIOBehavior.ERROR


def test_blocking_io_warning_is_runtime_warning() -> None:
    """HassetteBlockingIOWarning is a subclass of RuntimeWarning."""
    assert issubclass(HassetteBlockingIOWarning, RuntimeWarning)


def test_blocking_io_warning_integrates_with_filterwarnings() -> None:
    """HassetteBlockingIOWarning escalates to exception under filterwarnings('error')."""
    with warnings.catch_warnings():
        warnings.filterwarnings("error", category=HassetteBlockingIOWarning)
        with pytest.raises(HassetteBlockingIOWarning):
            warnings.warn("blocking io test", HassetteBlockingIOWarning, stacklevel=1)


def test_default_blocking_io_behavior_is_warn() -> None:
    """DEFAULT_BLOCKING_IO_BEHAVIOR is WARN."""
    assert DEFAULT_BLOCKING_IO_BEHAVIOR is BlockingIOBehavior.WARN


def test_resolve_default_when_both_none() -> None:
    """With no per-app and no global config set, resolve returns WARN."""
    _cfg = types.SimpleNamespace(blocking_io=types.SimpleNamespace(behavior=None))
    _hass = types.SimpleNamespace(config=_cfg)

    class _MockOwner:
        app_config = types.SimpleNamespace(blocking_io_behavior=None)
        hassette = _hass

    result = resolve_blocking_io_behavior(_MockOwner())
    assert result is BlockingIOBehavior.WARN


def test_resolve_per_app_wins_over_global() -> None:
    """Per-app blocking_io_behavior overrides global config."""
    _cfg = types.SimpleNamespace(blocking_io=types.SimpleNamespace(behavior=BlockingIOBehavior.WARN))
    _hass = types.SimpleNamespace(config=_cfg)

    class _MockOwner:
        app_config = types.SimpleNamespace(blocking_io_behavior=BlockingIOBehavior.IGNORE)
        hassette = _hass

    result = resolve_blocking_io_behavior(_MockOwner())
    assert result is BlockingIOBehavior.IGNORE  # per-app wins


def test_resolve_global_wins_when_per_app_none() -> None:
    """Global blocking_io.behavior is used when per-app is None."""
    _cfg = types.SimpleNamespace(blocking_io=types.SimpleNamespace(behavior=BlockingIOBehavior.ERROR))
    _hass = types.SimpleNamespace(config=_cfg)

    class _MockOwner:
        app_config = types.SimpleNamespace(blocking_io_behavior=None)
        hassette = _hass

    result = resolve_blocking_io_behavior(_MockOwner())
    assert result is BlockingIOBehavior.ERROR  # global wins when per-app is None


def test_resolve_per_app_ignore_suppresses_global_error() -> None:
    """Per-app IGNORE overrides a global ERROR setting."""
    _cfg = types.SimpleNamespace(blocking_io=types.SimpleNamespace(behavior=BlockingIOBehavior.ERROR))
    _hass = types.SimpleNamespace(config=_cfg)

    class _MockOwner:
        app_config = types.SimpleNamespace(blocking_io_behavior=BlockingIOBehavior.IGNORE)
        hassette = _hass

    result = resolve_blocking_io_behavior(_MockOwner())
    assert result is BlockingIOBehavior.IGNORE


def test_resolve_string_values_coerce() -> None:
    """String enum values coerce correctly during resolution."""
    _cfg = types.SimpleNamespace(blocking_io=types.SimpleNamespace(behavior="error"))
    _hass = types.SimpleNamespace(config=_cfg)

    class _MockOwner:
        app_config = types.SimpleNamespace(blocking_io_behavior=None)
        hassette = _hass

    result = resolve_blocking_io_behavior(_MockOwner())
    assert result is BlockingIOBehavior.ERROR


def test_resolve_missing_app_config_falls_back_to_default() -> None:
    """Missing app_config attribute falls back to hardcoded WARN default."""

    class _MockOwner:
        pass  # no app_config, no hassette

    result = resolve_blocking_io_behavior(_MockOwner())
    assert result is BlockingIOBehavior.WARN


def test_resolve_none_owner_falls_back_to_default() -> None:
    """None owner falls back to hardcoded WARN default without raising."""
    result = resolve_blocking_io_behavior(None)
    assert result is BlockingIOBehavior.WARN


def test_app_config_has_blocking_io_behavior_field() -> None:
    """AppConfig has blocking_io_behavior field defaulting to None."""
    config = AppConfig()
    assert hasattr(config, "blocking_io_behavior")
    assert config.blocking_io_behavior is None


def test_app_config_blocking_io_behavior_accepts_enum() -> None:
    """AppConfig blocking_io_behavior accepts BlockingIOBehavior values."""
    config = AppConfig(blocking_io_behavior=BlockingIOBehavior.IGNORE)
    assert config.blocking_io_behavior is BlockingIOBehavior.IGNORE


def test_app_config_blocking_io_behavior_accepts_string() -> None:
    """AppConfig blocking_io_behavior coerces string values to enum."""
    config = AppConfig(blocking_io_behavior="error")
    assert config.blocking_io_behavior is BlockingIOBehavior.ERROR


def test_app_config_blocking_io_behavior_ignore_resolves(tmp_path: Path) -> None:
    """Setting blocking_io_behavior='ignore' on AppConfig resolves to IGNORE."""
    app_config = AppConfig(blocking_io_behavior=BlockingIOBehavior.IGNORE)
    _hass = types.SimpleNamespace(config=make_test_config(data_dir=tmp_path))

    class _MockOwner:
        pass

    owner = _MockOwner()
    owner.app_config = app_config  # pyright: ignore[reportAttributeAccessIssue]
    owner.hassette = _hass  # pyright: ignore[reportAttributeAccessIssue]

    result = resolve_blocking_io_behavior(owner)
    assert result is BlockingIOBehavior.IGNORE


def test_hassette_config_has_blocking_io_field(tmp_path: Path) -> None:
    """HassetteConfig has blocking_io field with a BlockingIODetectionConfig default."""
    config = make_test_config(data_dir=tmp_path)
    assert hasattr(config, "blocking_io")
    assert isinstance(config.blocking_io, BlockingIODetectionConfig)


def test_blocking_io_detection_config_defaults() -> None:
    """BlockingIODetectionConfig has correct defaults."""
    cfg = BlockingIODetectionConfig()
    assert cfg.behavior is None
    assert cfg.watchdog_enabled is True
    assert cfg.lag_threshold_seconds == pytest.approx(0.1)
    assert cfg.watchdog_interval_seconds == pytest.approx(0.25)
    assert cfg.capture_stack_on_block is True
    assert cfg.deep_detection_enabled is None
    assert cfg.allow_deep_detection_in_prod is False


def test_blocking_io_detection_config_accepts_behavior_enum() -> None:
    """BlockingIODetectionConfig.behavior accepts BlockingIOBehavior values."""
    cfg = BlockingIODetectionConfig(behavior=BlockingIOBehavior.WARN)
    assert cfg.behavior is BlockingIOBehavior.WARN


def test_blocking_io_detection_config_accepts_behavior_string() -> None:
    """BlockingIODetectionConfig.behavior coerces string values to enum."""
    cfg = BlockingIODetectionConfig(behavior="ignore")
    assert cfg.behavior is BlockingIOBehavior.IGNORE


def test_resolve_uses_global_blocking_io_config(tmp_path: Path) -> None:
    """resolve_blocking_io_behavior reads global HassetteConfig.blocking_io.behavior."""
    config = make_test_config(data_dir=tmp_path)
    config.blocking_io.behavior = BlockingIOBehavior.ERROR
    _hass = types.SimpleNamespace(config=config)

    class _MockOwner:
        app_config = types.SimpleNamespace(blocking_io_behavior=None)
        hassette = _hass

    result = resolve_blocking_io_behavior(_MockOwner())
    assert result is BlockingIOBehavior.ERROR
