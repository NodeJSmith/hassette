"""Token resolution for the web API's bearer-token/session-cookie fallback.

Resolves the credential used by ``AuthDep``/the default-deny middleware to validate
``Authorization: Bearer <token>`` headers and mint session cookies. See
``design/specs/091-web-api-auth/design.md`` (Architecture → Credential model) for the full
mechanism this implements.
"""

import os
import secrets
from contextlib import suppress
from logging import getLogger
from pathlib import Path

from hassette.config.models import WebApiConfig
from hassette.exceptions import AuthTokenWriteError
from hassette.utils.net_utils import format_host

LOGGER = getLogger(__name__)

TOKEN_FILENAME = ".web_api_token"  # noqa: S105 — a filename, not a hardcoded credential
"""Name of the persisted token file, relative to ``data_dir``."""

TOKEN_BYTE_LENGTH = 32
"""Byte length passed to ``secrets.token_urlsafe()`` when generating a fresh token."""


def resolve_auth_token(config: WebApiConfig, data_dir: Path) -> str:
    """Resolve the web API's bearer-token/session-cookie credential.

    Tries, in order:

    1. ``config.auth_token`` if explicitly configured (non-``None``) and non-blank. A
       configured value that is empty or whitespace-only is treated identically to "not
       configured" and falls through to step 2 — accepting it as-is would resolve to a
       publicly-guessable empty credential (e.g. from ``AUTH_TOKEN=""`` in the
       environment), which ``check_bearer_token`` would then accept from any caller
       presenting an empty token.
    2. An existing ``<data_dir>/.web_api_token`` file. A corrupt or unreadable file
       (empty, undecodable, or an OS-level read failure) is treated identically to
       "no file exists" — the failure is logged at ERROR and resolution falls through
       to step 3 rather than crashing.
    3. A freshly generated ``secrets.token_urlsafe(32)`` value, persisted atomically
       (temp file in the same directory + atomic rename, mode ``0600``) to
       ``<data_dir>/.web_api_token``.

    Whichever branch fires is logged at INFO with a distinct, identifiable message on
    every startup, not only the generate branch — so an operator who lost a
    previously-working token file (volume not migrated, ``docker compose down -v``) sees
    "loaded existing file" vs. "generated a new one" as a distinguishable event, not
    silence.

    Args:
        config: The web API config. Its ``host``/``port`` are used to build the
            ready-to-use login URL logged on the generate branch.
        data_dir: Directory the token file is read from/written to. Callers pass
            ``HassetteConfig.data_dir`` — this function does not resolve it itself.

    Returns:
        The plaintext token, unwrapped from ``SecretStr`` when it came from config.

    Raises:
        AuthTokenWriteError: The freshly generated token could not be persisted to disk
            (permissions, read-only filesystem, full disk). Startup fails loudly rather
            than falling back to an ephemeral in-memory token — see the exception's
            docstring for why silent fallback is unacceptable here.
    """
    if config.auth_token is not None:
        configured_token = config.auth_token.get_secret_value().strip()
        if configured_token:
            LOGGER.info("Using configured web API auth_token")
            return configured_token
        LOGGER.error("Configured web API auth_token is blank; generating a new token instead")

    token_path = data_dir / TOKEN_FILENAME
    existing_token = _read_existing_token(token_path)
    if existing_token is not None:
        LOGGER.info("Loaded existing web API auth_token from %s", token_path)
        return existing_token

    token = secrets.token_urlsafe(TOKEN_BYTE_LENGTH)
    _write_token_atomic(token_path, token)
    login_url = f"http://{format_host(config.host)}:{config.port}"
    LOGGER.info(
        "Generated new web API auth_token, written to %s. Open %s to log in.",
        token_path,
        login_url,
    )
    return token


def _read_existing_token(token_path: Path) -> str | None:
    """Read an existing token file, treating a corrupt/unreadable file as "no file".

    Returns ``None`` (never raises) when the file doesn't exist, is empty, contains
    undecodable bytes, or otherwise fails to read — each of those is logged at ERROR
    so the fallback to a fresh token is visible, not silent.
    """
    if not token_path.exists():
        return None

    try:
        content = token_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        LOGGER.exception(
            "Web API auth token file %s could not be read; generating a new token",
            token_path,
        )
        return None

    if not content:
        LOGGER.error(
            "Web API auth token file %s is empty; generating a new token",
            token_path,
        )
        return None

    return content


def _write_token_atomic(token_path: Path, token: str) -> None:
    """Write ``token`` to ``token_path`` atomically, mode ``0600``.

    Writes to a temp file in the same directory as ``token_path`` (not ``/tmp``, which
    may be a different filesystem and would break the rename's atomicity guarantee),
    then swaps it into place with ``Path.replace()`` (an atomic rename on POSIX). Any
    failure along the way (including creating the parent directory) is wrapped in
    ``AuthTokenWriteError`` naming the exact path and OS error, and any
    partially-written temp file is cleaned up on a best-effort basis.
    """
    tmp_path = token_path.with_name(f"{token_path.name}.tmp-{os.getpid()}")
    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token)
        tmp_path.replace(token_path)
    except OSError as exc:
        with suppress(OSError):
            tmp_path.unlink()
        raise AuthTokenWriteError(token_path, exc) from exc
