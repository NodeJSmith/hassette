---
task_id: "T11"
title: "Extend test_auth.py with the full assembled auth-flow coverage"
status: "planned"
depends_on: ["T01", "T02", "T03", "T04", "T05", "T06"]
implements: ["AC#2", "AC#3", "AC#4", "AC#5", "AC#6", "AC#15", "AC#18"]
---

## Summary

Extends `tests/integration/web_api/test_auth.py` (created by T05, extended by T06) with the
end-to-end assertions that require the full assembled system — config, token resolution,
trusted-proxy matching, bearer/cookie auth, the default-deny middleware, and the login route all
wired together through the actual FastAPI app via `httpx.AsyncClient`/`ASGITransport`. The individual
mechanisms were already unit-tested in isolation by T02-T04; this task proves they work correctly
composed, which is a genuinely different claim (each piece can be individually correct while the
composition is wrong — wrong exemption order, wrong middleware registration order, a peer-check that
works standalone but never actually receives the right `scope["client"]` through the real app).

## Target Files

- modify: `tests/integration/web_api/test_auth.py` — add the assertions below
- read: `tests/integration/web_api/conftest.py:16-46,55-66` — `mock_hassette`, `app`, `client` fixtures
- read: `tests/integration/web_api/CLAUDE.md` — directory-specific fixture conventions

## Prompt

Read design.md's `## Acceptance Criteria` AC#2 through AC#6, AC#15, AC#18 and their mapped FRs, and
`## Test Strategy → New Test Coverage`'s `tests/integration/web_api/test_auth.py` bullet in full —
that bullet is the authoritative list of assertions this task must add.

Using `create_hassette_stub(auth_enabled=True)` (T01) and `httpx.AsyncClient`/`ASGITransport` (the
existing `client` fixture pattern at `tests/integration/web_api/conftest.py:55-66`), add tests for:

- A wrong bearer token returns 401; a correct `Authorization: Bearer <token>` header returns 200
  (AC#2).
- A correct session cookie (minted via T04's mint function directly, or via `POST
  /api/auth/session`) returns 200 (AC#3).
- A request whose `ASGITransport` client address matches a `trusted_proxies` IP or CIDR entry returns
  200 with no credential (AC#4) — `ASGITransport` supports setting the simulated client address; use
  that rather than trying to spoof it via headers.
- A request whose client address matches a `trusted_proxies` hostname entry (mock DNS resolution at
  startup) returns 200 with no credential; then simulate T03's periodic-refresh tick (call the
  refresh function directly with a changed mock DNS result, as T03's own unit test does) and confirm
  a request from the *new* resolved address now also returns 200 (AC#5).
- A spoofed `X-Forwarded-For: <trusted-IP>` header sent from an untrusted `ASGITransport` client
  address is rejected exactly like any other unauthenticated request — 401, not 200 (AC#6). This is
  the test that most directly proves FR#3's structural guarantee actually holds end-to-end, not just
  in the matcher function's isolated signature.
- A cookie minted more than `session_ttl` seconds ago (construct one directly with a stale embedded
  timestamp via T04's mint function, or monkeypatch time) is rejected on the next request (AC#15).
- A request from a `trusted_proxies` peer with `X-Forwarded-Proto: https` results in a
  `Secure`-flagged cookie on the subsequent `POST /api/auth/session`; the same request from a
  non-trusted peer with the same header spoofed does not produce a `Secure` cookie (AC#18).

## Focus

- This task's entire value is testing *composition*, not re-testing individual mechanisms T02-T04
  already covered at the unit level — every test here should go through the real FastAPI app (the
  `app`/`client` fixtures), not call `web/auth.py` functions directly, except where directly minting
  a cookie/setting a stale timestamp is the only practical way to construct a specific test
  precondition (AC#15, AC#3).
- `ASGITransport`'s ability to set a simulated client address is the mechanism for AC#4/AC#5/AC#6 —
  check `httpx`'s `ASGITransport` API (via context7 if unfamiliar) for exactly how to set
  `scope["client"]` on a test request; this is not the same as setting a header.
- Read `tests/integration/web_api/CLAUDE.md` before adding fixtures — this directory has documented
  conventions (the `db_degrades_to` pattern, `mock_hassette`/`runtime_query_service`/`app`/`client`
  fixture names) that new tests should follow rather than reinvent.

## Verify

- [ ] AC#2: Test confirms a wrong bearer token returns 401 and a correct one returns 200.
- [ ] AC#3: Test confirms a correct session cookie returns 200.
- [ ] AC#4: Test confirms a client address matching a `trusted_proxies` IP/CIDR entry returns 200 with no credential.
- [ ] AC#5: Test confirms a client address matching a `trusted_proxies` hostname entry returns 200, and confirms the trusted set updates after a simulated periodic-refresh tick.
- [ ] AC#6: Test confirms a spoofed `X-Forwarded-For` header from an untrusted client address is rejected (401), not treated as trusted.
- [ ] AC#15: Test confirms a cookie minted more than `session_ttl` seconds ago is rejected, and one within the TTL is accepted.
- [ ] AC#18: Test confirms a trusted peer with `X-Forwarded-Proto: https` gets a `Secure`-flagged cookie from `POST /api/auth/session`, and a non-trusted peer with the same spoofed header does not.
