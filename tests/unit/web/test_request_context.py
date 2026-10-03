"""HassetteContextMiddleware restores the prior context even when the wrapped app raises."""

from unittest.mock import MagicMock

import pytest
from starlette.types import Receive, Scope, Send

from hassette import context
from hassette.web.request_context import HassetteContextMiddleware


async def test_context_restored_when_inner_app_raises() -> None:
    prior_hassette = MagicMock(name="prior_hassette")
    prior_config = MagicMock(name="prior_config")
    hassette = MagicMock(name="hassette")
    seen: dict[str, bool] = {}

    async def raising_app(_scope: Scope, _receive: Receive, _send: Send) -> None:
        seen["instance"] = context.get_hassette() is hassette
        seen["config"] = context.get_hassette_config() is hassette.config
        raise RuntimeError("boom")

    middleware = HassetteContextMiddleware(app=raising_app, hassette=hassette)

    with (
        context.use(context.HASSETTE_INSTANCE, prior_hassette),
        context.use_hassette_config(prior_config),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await middleware({"type": "http"}, MagicMock(), MagicMock())

        assert seen == {"instance": True, "config": True}
        assert context.get_hassette() is prior_hassette
        assert context.get_hassette_config() is prior_config
