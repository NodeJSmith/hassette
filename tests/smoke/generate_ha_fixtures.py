"""
Run once to regenerate tests/fixtures/ha-config/.storage/auth.
Output is committed to the repo.

Usage: uv run python tests/smoke/generate_ha_fixtures.py
"""
import bcrypt
import json
from pathlib import Path

SMOKE_TOKEN = "hassette-smoke-test-token"
USER_ID = "hassette-test-user-0000-000000000000"
CREDENTIAL_ID = "hassette-test-cred-0000-000000000000"
TOKEN_ID = "hassette-test-token-000-000000000000"

token_hash = bcrypt.hashpw(SMOKE_TOKEN.encode(), bcrypt.gensalt(rounds=4)).decode()

auth = {
    "version": 7,
    "minor_version": 1,
    "key": "auth",
    "data": {
        "users": [
            {
                "id": USER_ID,
                "group_ids": ["system-admin"],
                "local_only": False,
                "name": "Smoke Test Admin",
                "is_active": True,
                "is_owner": True,
                "system_generated": False,
            }
        ],
        "groups": [],
        "credentials": [
            {
                "id": CREDENTIAL_ID,
                "user_id": USER_ID,
                "auth_provider_type": "homeassistant",
                "auth_provider_id": None,
                "data": {
                    "username": "admin",
                    "password": bcrypt.hashpw(b"admin", bcrypt.gensalt(rounds=4)).decode(),
                },
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "access_tokens": [
            {
                "id": TOKEN_ID,
                "user_id": USER_ID,
                "client_id": None,
                "client_name": "Hassette Smoke Tests",
                "client_icon": None,
                "token_type": "long_lived_access_token",
                "created_at": "2026-01-01T00:00:00+00:00",
                "access_token_expiration": None,
                "expire_at": None,
                "token": token_hash,
            }
        ],
        "refresh_tokens": [],
    },
}

out = Path("tests/fixtures/ha-config/.storage/auth")
out.write_text(json.dumps(auth, indent=2))
print(f"Wrote {out}")
print(f"Token: {SMOKE_TOKEN}")
