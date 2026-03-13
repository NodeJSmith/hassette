"""Regenerate tests/fixtures/ha-config/.storage/ auth files.

Run once from the repo root when the fixture format needs to change.
Output files are committed to the repo.

Usage: uv run python tests/smoke/generate_ha_fixtures.py
"""

import base64
import hashlib
import hmac
import json
from pathlib import Path

# ── Deterministic IDs (never change these) ──────────────────────────────────
USER_ID = "00000000000000000000000000000001"
CREDENTIAL_ID = "00000000000000000000000000000002"
TOKEN_ID = "00000000000000000000000000000003"

# 64-byte HS256 signing key for the LLAT JWT (128 hex chars = 64 bytes)
JWT_KEY_HEX = (
    "0000000000000000000000000000000000000000000000000000000000000001"
    "0000000000000000000000000000000000000000000000000000000000000002"
)

# Raw token field (63 bytes = 126 hex chars) — used for OAuth refresh, not LLAT auth
RAW_TOKEN_HEX = "0" * 126

# Fixed timestamps: issued 2026-01-01T00:00:00Z, expires 2036-01-01T00:00:00Z
IAT = 1735689600
EXP = IAT + 315360000  # +3650 days ≈ 10 years

# Pre-computed bcrypt hash of "smoke" with rounds=4.
# Smoke tests authenticate with the LLAT JWT, not a password.
# This value only needs to be a valid bcrypt hash so HA boots without errors.
ADMIN_PASSWORD_HASH_B64 = (
    "JDJiJDA0JDR6MnVBRHdVenU4bzRZbmM5M2twYS5pUXI2RHZXS3pLWHdaRTdqSGovU3NtRjg1WGpMRkd5"
)

STORAGE = Path("tests/fixtures/ha-config/.storage")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_jwt(token_id: str, jwt_key_hex: str, iat: int, exp: int) -> str:
    """Create an HS256 JWT for use as an HA long-lived access token.

    HA verifies the token by:
    1. Decoding the JWT to get ``iss`` (= token_id)
    2. Looking up the refresh_token entry with matching ``id``
    3. Re-verifying the JWT signature using that entry's ``jwt_key``
    """
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(
        json.dumps({"iss": token_id, "iat": iat, "exp": exp}, separators=(",", ":")).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    # HA passes jwt_key directly to PyJWT as a string; PyJWT encodes it as UTF-8.
    # Use the same encoding so the signature matches.
    key = jwt_key_hex.encode()
    sig = hmac.new(key, signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"


def write_auth() -> None:
    auth = {
        "version": 1,
        "minor_version": 1,
        "key": "auth",
        "data": {
            "users": [
                {
                    "id": USER_ID,
                    "group_ids": ["system-admin"],
                    "is_owner": True,
                    "is_active": True,
                    "name": "Smoke Test Admin",
                    "system_generated": False,
                    "local_only": False,
                }
            ],
            "groups": [
                {"id": "system-admin", "name": "Administrators"},
                {"id": "system-users", "name": "Users"},
                {"id": "system-read-only", "name": "Read Only"},
            ],
            "credentials": [
                {
                    "id": CREDENTIAL_ID,
                    "user_id": USER_ID,
                    "auth_provider_type": "homeassistant",
                    "auth_provider_id": None,
                    "data": {"username": "admin"},
                }
            ],
            "refresh_tokens": [
                {
                    "id": TOKEN_ID,
                    "user_id": USER_ID,
                    "client_id": None,
                    "client_name": "Hassette Smoke Tests",
                    "client_icon": None,
                    "token_type": "long_lived_access_token",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "access_token_expiration": 315360000.0,
                    "token": RAW_TOKEN_HEX,
                    "jwt_key": JWT_KEY_HEX,
                    "last_used_at": None,
                    "last_used_ip": None,
                    "expire_at": None,
                    "credential_id": None,
                    "version": "2025.3.4",
                }
            ],
        },
    }
    out = STORAGE / "auth"
    out.write_text(json.dumps(auth, indent=2))
    print(f"Wrote {out}")


def write_auth_provider() -> None:
    data = {
        "version": 1,
        "minor_version": 1,
        "key": "auth_provider.homeassistant",
        "data": {
            "users": [
                {
                    "username": "admin",
                    "password": ADMIN_PASSWORD_HASH_B64,
                }
            ]
        },
    }
    out = STORAGE / "auth_provider.homeassistant"
    out.write_text(json.dumps(data, indent=2))
    print(f"Wrote {out}")


def write_onboarding() -> None:
    data = {
        "version": 4,
        "minor_version": 1,
        "key": "onboarding",
        "data": {"done": ["user", "core_config", "analytics", "integration"]},
    }
    out = STORAGE / "onboarding"
    out.write_text(json.dumps(data, indent=2))
    print(f"Wrote {out}")


if __name__ == "__main__":
    bearer_token = make_jwt(TOKEN_ID, JWT_KEY_HEX, IAT, EXP)
    write_auth()
    write_auth_provider()
    write_onboarding()
    print(f"\nBearer token (HA_TOKEN in conftest.py):\n{bearer_token}")
