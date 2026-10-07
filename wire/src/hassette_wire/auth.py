from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_SESSION_TOKEN_LENGTH = 4096
"""Upper bound on the ``token`` field of :class:`SessionRequest`.

Generated tokens are ``secrets.token_urlsafe(32)`` — 43 characters — but a deployment may supply
its own, so the cap is set far above any plausible real token rather than tight to the generated
shape.
"""


class SessionRequest(BaseModel):
    """Request body for ``POST /api/auth/session``: exchanges a bearer token for a session cookie."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    token: str = Field(max_length=MAX_SESSION_TOKEN_LENGTH)
    """Bearer token to exchange for a session cookie.

    The server rejects a value longer than the field's maximum length with a 422.
    """


class SessionResponse(BaseModel):
    """Response for ``POST /api/auth/session`` when the token is accepted.

    The session cookie arrives in the ``Set-Cookie`` response header; this body only confirms
    success.
    """

    status: Literal["ok"] = "ok"
