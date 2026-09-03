"""Tests for the public API surface of hassette.testing.

Verifies Tier 1 symbol set in __all__, Tier 2 exclusion,
and star-import behavior.
"""

import types

import hassette.testing as test_utils
from hassette.testing import HassetteHarness

TIER1_SYMBOLS = {
    "ApiCall",
    "AppConfigurationError",
    "AppTestHarness",
    "DrainError",
    "DrainFailure",
    "DrainTimeout",
    "EventCapture",
    "HassetteHarness",
    "RecordingApi",
    "build_harness",
    "create_call_service_event",
    "create_state_change_event",
    "dummy_cache",
    "make_full_state_change_event",
    "make_light_state_dict",
    "make_sensor_state_dict",
    "make_state_dict",
    "make_switch_state_dict",
    "make_test_config",
    "make_typed_state",
    "wait_for",
}


def test_tier1_in_all() -> None:
    """__all__ contains exactly the Tier 1 symbols — no more, no less."""
    assert set(test_utils.__all__) == TIER1_SYMBOLS


def test_tier2_importable() -> None:
    """Tier 1 symbols (e.g. HassetteHarness) are importable from hassette.testing."""
    assert HassetteHarness is not None


def test_tier2_not_in_all() -> None:
    """Tier 2 symbols are not in __all__."""
    assert "make_mock_hassette" not in test_utils.__all__
    assert "SimpleTestServer" not in test_utils.__all__
    assert "preserve_config" not in test_utils.__all__
    assert "AppConfigurationError" in test_utils.__all__  # Tier 1 — users need to catch this


def test_star_import_only_tier1() -> None:
    """From hassette.testing import * brings only Tier 1 symbols into namespace."""
    # Create a fresh module to simulate star import
    fresh = types.ModuleType("_star_test")
    exec("from hassette.testing import *", fresh.__dict__)

    # Every Tier 1 symbol must be present
    for sym in TIER1_SYMBOLS:
        assert sym in fresh.__dict__, f"Tier 1 symbol {sym!r} missing from star import"

    # Tier 2 symbols must NOT be present
    tier2_samples = ["make_mock_hassette", "SimpleTestServer", "preserve_config"]
    for sym in tier2_samples:
        assert sym not in fresh.__dict__, f"Tier 2 symbol {sym!r} leaked into star import"
