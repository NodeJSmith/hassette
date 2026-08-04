"""Login exchange endpoint for the Hassette Web API."""

from fastapi import APIRouter, HTTPException, Request, Response

from hassette.web.auth import (
    SESSION_COOKIE_NAME,
    check_bearer_token,
    get_trusted_proxies,
    mint_session_cookie,
    peer_address,
    should_set_secure_cookie_flag,
)
from hassette.web.dependencies import AuthDep, HassetteDep
from hassette.web.models import SessionRequest, SessionResponse

router = APIRouter(tags=["auth"])


@router.post("/auth/session", response_model=SessionResponse, responses={401: {"description": "Invalid token"}})
async def create_session(
    body: SessionRequest,
    request: Request,
    response: Response,
    hassette: HassetteDep,
    resolved_token: AuthDep,
) -> SessionResponse:
    """Exchange a bearer token for an `HttpOnly`/`SameSite=Strict` session cookie.

    Exempt from ``DefaultDenyMiddleware``'s default-deny by path (see
    ``web/middleware.py``'s ``EXEMPT_ROUTES``) -- this handler performs its own
    body-based token validation instead, since it's the one endpoint that must be
    reachable with zero prior credential (see design.md's Functional Requirements and
    the Edge Case "POST /api/auth/session with a correct token but no existing cookie").
    """
    if resolved_token is None or not check_bearer_token(body.token, resolved_token):
        raise HTTPException(status_code=401, detail="Invalid token")

    trusted_proxies = get_trusted_proxies(request.app.state)
    client_address = peer_address(request)
    secure = should_set_secure_cookie_flag(client_address, request.headers.get("x-forwarded-proto"), trusted_proxies)

    cookie_value = mint_session_cookie(resolved_token)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        cookie_value,
        max_age=hassette.config.web_api.session_ttl,
        httponly=True,
        samesite="strict",
        secure=secure,
    )
    return SessionResponse()
