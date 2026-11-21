"""Messages and guards on the integration error types."""

import pytest

from hassette.integration.declarations import CommandDispatchResult, IntegrationPlatform
from hassette.integration.errors import REJECTION_REASONS, IntegrationCommandRejectedError


def test_every_non_dispatched_result_has_a_rejection_reason() -> None:
    assert set(REJECTION_REASONS) == set(CommandDispatchResult) - {CommandDispatchResult.DISPATCHED}


def test_dispatched_is_not_a_rejection_reason() -> None:
    with pytest.raises(ValueError, match="not a rejection reason"):
        IntegrationCommandRejectedError(CommandDispatchResult.DISPATCHED, "app.0", "feed", IntegrationPlatform.BUTTON)
