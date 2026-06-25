"""Integration test for preserve_config round-tripping a SecretStr token.

preserve_config must restore a SecretStr token unchanged after a scope exits,
without poisoning it to the masked placeholder (``"**********"``).
"""

from hassette.test_utils.config import TEST_TOKEN, make_test_config
from hassette.test_utils.harness import preserve_config


def test_preserve_config_round_trips_secretstr_token(tmp_path) -> None:
    """preserve_config restores the original SecretStr token after a mutation."""
    config = make_test_config(data_dir=tmp_path)
    assert config.token is not None
    original_value = config.token.get_secret_value()

    with preserve_config(config):
        config.token = "mutated-token"  # pyright: ignore[reportAttributeAccessIssue]
        assert config.token.get_secret_value() == "mutated-token"

    assert config.token is not None
    assert config.token.get_secret_value() == original_value
    # Confirm the masked placeholder was never stored as the token value
    assert config.token.get_secret_value() != "**********"


def test_preserve_config_restores_none_token(tmp_path) -> None:
    """preserve_config correctly restores a None token."""
    config = make_test_config(data_dir=tmp_path, token=None)
    assert config.token is None

    with preserve_config(config):
        config.token = "added-inside-scope"  # pyright: ignore[reportAttributeAccessIssue]
        assert config.token is not None

    assert config.token is None


def test_preserve_config_token_not_poisoned_to_masked_value(tmp_path) -> None:
    """The restored token carries the real secret, not the masked repr.

    Before the model_copy(deep=True) fix, model_dump() would return
    ``"**********"`` for SecretStr fields (Python-mode serialisation).
    Restoring via setattr with validate_assignment=True would then coerce
    ``"**********"`` into SecretStr("**********") — the wrong value.
    This test pins that the restoration path is free of that bug.
    """
    config = make_test_config(data_dir=tmp_path)
    assert config.token is not None
    expected = config.token.get_secret_value()
    assert expected == TEST_TOKEN

    with preserve_config(config):
        # Simulate a test that mutates the token
        config.token = "temporary"  # pyright: ignore[reportAttributeAccessIssue]

    restored = config.token
    assert restored is not None
    assert restored.get_secret_value() == expected, (
        f"Token was poisoned: got {restored.get_secret_value()!r}, expected {expected!r}"
    )
