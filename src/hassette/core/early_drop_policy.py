"""Early-drop reconnect classification and backoff for :class:`~hassette.core.websocket_service.WebsocketService`.

Extracted from ``websocket_service.py`` to keep that module under the project's file-size
guideline — these are the pieces that classify and pace a *reconnect after an early drop*
(a connection loss shortly after establishing, worth retrying in place rather than propagating
as a genuine failure). Deliberately not named or merged with :mod:`hassette.core.retry_policy`,
which is a different mechanism entirely: the shared retry-attempt budget for a single HA
request/reply exchange (``subscribe_events``/``send_and_wait``/REST), not reconnect behavior.
Connection-state transitions, message dispatch, and event emission stay in the service itself
since they touch instance state these functions don't need.
"""

import asyncio
import random
import time
import typing
from logging import Logger

from aiohttp import ServerDisconnectedError

from hassette.exceptions import RetryableConnectionClosedError

if typing.TYPE_CHECKING:
    from hassette.config.models import WebSocketConfig

# Subset of connection-drop exceptions that qualify for early-drop retry.
# Excludes ClientConnectorError and CouldNotFindHomeAssistantError — those indicate
# the server is unreachable, not that it dropped a post-auth connection.
EARLY_DROP_RETRYABLE = (RetryableConnectionClosedError, ServerDisconnectedError)

EARLY_DROP_BACKOFF_BASE = 2
"""Exponential base for early-drop backoff, unrelated to state_proxy.py's
SYNC_RETRY_BACKOFF_BASE — a different retry mechanism (local cache-read retry vs. reconnect
backoff) that coincidentally also uses base 2."""


def log_resilience_budget(config: "WebSocketConfig", logger: Logger, budget_intensity: int) -> None:
    """Log the early-drop and connection retry budget that bounds recovery time."""
    max_early_drops = config.early_drop_max_retries
    max_recovery = config.max_recovery_seconds
    logger.info(
        "WebSocket resilience budget: max ~%.0f minutes to permanent shutdown "
        "(early-drop: %d retries capped at %ds, connection: %d retries, service: %d restarts)",
        max_recovery / 60,
        max_early_drops,
        int(max_recovery),
        config.connect_retry_max_attempts,
        budget_intensity,
    )


def compute_recovery_windows(connected_at: float | None, recovery_started_at: float | None) -> tuple[float, float]:
    """Compute (seconds since last connect, seconds since recovery began) for drop classification."""
    elapsed = (time.monotonic() - connected_at) if connected_at is not None else float("inf")
    recovery_elapsed = (time.monotonic() - recovery_started_at) if recovery_started_at is not None else 0.0
    return elapsed, recovery_elapsed


def is_early_drop(
    config: "WebSocketConfig", exc: Exception, early_drop_attempts: int, elapsed: float, recovery_elapsed: float
) -> bool:
    """Classify exc as an early drop (retry in place) versus a genuine failure (propagate)."""
    return (
        elapsed < config.early_drop_stable_window_seconds
        and isinstance(exc, EARLY_DROP_RETRYABLE)
        and early_drop_attempts < config.early_drop_max_retries
        and recovery_elapsed < config.max_recovery_seconds
    )


async def early_drop_backoff(config: "WebSocketConfig", attempt: int) -> None:
    """Compute and sleep for an exponential-jitter backoff after an early drop.

    Args:
        config: The websocket config, for the early-drop backoff settings.
        attempt: The current attempt number (1-based).
    """
    backoff = min(
        config.early_drop_backoff_initial_seconds * (EARLY_DROP_BACKOFF_BASE ** (attempt - 1)),
        config.early_drop_backoff_max_seconds,
    ) + random.uniform(0, config.early_drop_backoff_initial_seconds)
    await asyncio.sleep(backoff)
