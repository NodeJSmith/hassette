from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_SESSION_TOKEN_LENGTH = 4096
"""Upper bound on the ``token`` field of :class:`SessionRequest`.

Generated tokens are ``secrets.token_urlsafe(32)`` — 43 characters — but a deployment may supply
its own, so the cap is set far above any plausible real token rather than tight to the generated
shape.
"""


class SessionRequest(BaseModel):
    """Request body for POST /api/auth/session.

    The pinned wire contract for the login exchange (design.md's Middleware and routing
    section): ``{"token": "<bearer-token>"}``. The backend (this route) and the frontend
    (``postSession()`` in ``client.ts``) target this exact field name independently.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    token: str = Field(max_length=MAX_SESSION_TOKEN_LENGTH)
    """Bearer token to exchange for a session cookie.

    The server rejects a value longer than ``maxLength`` with a 422.
    """


class SessionResponse(BaseModel):
    """Response for POST /api/auth/session on a correct token.

    The session cookie itself travels via the ``Set-Cookie`` response header, minted by
    ``mint_session_cookie()`` — this body just confirms success for callers that inspect
    the JSON payload rather than only the status code.
    """

    status: Literal["ok"] = "ok"
