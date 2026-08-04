---
task_id: "T04"
title: "Add bearer token and session cookie mint/verify to web/auth.py"
status: "done"
depends_on: ["T01", "T02", "T03"]
implements: ["FR#6", "FR#7", "FR#8", "FR#20", "FR#22"]
---

## Summary

Extends `src/hassette/web/auth.py` with the always-available fallback credential mechanism: a
timing-safe bearer-token check, and a stateless HMAC-derived session cookie with mint/verify
functions and TTL enforcement. Also adds the function that decides whether a minted cookie should
carry the `Secure` flag, based on the same trusted-peer check T03 built plus the request's
`X-Forwarded-Proto` header.

## Target Files

- modify: `src/hassette/web/auth.py` — add bearer check, cookie mint/verify, Secure-flag decision
- modify: `tests/unit/web/test_auth.py` — unit tests
- read: `src/hassette/web/auth.py` — trusted-peer matcher from T03, reused (not duplicated) by the Secure-flag decision

## Prompt

Read design.md's `## Architecture → Credential model` (second paragraph, bearer/cookie half) and
`## Architecture → Cookie Secure flag` in full, plus FR#6, FR#7, FR#8, FR#20.

In `src/hassette/web/auth.py`, add:

1. **Bearer token check** — a function comparing a presented token against the resolved
   `auth_token` (from T02) via `secrets.compare_digest` (timing-safe; never `==`).
2. **Cookie mint** — given the resolved token, produce a cookie value that is HMAC-derived (keyed by
   the token itself, not a separate secret — no new secret material is introduced) over a random
   session id plus an embedded issuance timestamp. Stateless: no server-side session table, so it
   survives `WebApiService`'s `RestartType.TRANSIENT` restarts (FR#7).
3. **Cookie verify** — given a presented cookie value and the resolved token, recompute and compare
   the HMAC (timing-safe), and separately check the embedded issuance timestamp against
   `config.web_api.session_ttl` (added by T01) — reject if expired (FR#8).
4. **Secure-flag decision function** — takes the request's raw `scope["client"]` and its
   `X-Forwarded-Proto` header value, and returns whether the flag should be set. It must call T03's
   trusted-peer matcher on the raw client address first; only when that peer is trusted does it even
   look at `X-Forwarded-Proto`, and only sets `Secure=True` when that header says `https`. An
   untrusted peer's `X-Forwarded-Proto` is never consulted for anything (FR#20) — this is the same
   peer-trust decision T03 already makes, reused here, not a second parallel implementation of
   peer-trust logic.

5. **Renewal predicate** — a function answering "should this verified cookie be replaced?", returning
   `True` once the cookie's embedded issuance timestamp is older than half of
   `config.web_api.session_ttl`. T05's middleware calls this after a successful cookie verification
   and, when it returns `True`, mints a replacement via step 2 and sets it on the response (FR#22).
   Keep the predicate and the minting separate from the response handling — this task owns the
   *decision* and the *value*; T05 owns writing the `Set-Cookie` header.

**Every function in this task must treat a `None` resolved token as "never authenticates."** T05
deliberately allows `auth_enabled=True` with `app.state.auth_token = None` (its no-credential-401
tests are built that way), so `None` reaches the bearer check and the cookie verify on a real code
path. `secrets.compare_digest(presented, None)` raises `TypeError`, which would turn an intended 401
into a 500 — guard for `None` explicitly and return "not authenticated" rather than letting it reach
the comparison.

Do not implement `authorize_ws()` or the composed default-deny check here — that composition (which
calls both T03's matcher and this task's bearer/cookie checks together) is T05's job, in
`web/middleware.py`.

## Focus

- The Secure-flag function must call into T03's already-built peer-matcher, not reimplement peer
  comparison. If you find yourself writing a second IP/CIDR comparison here, stop — import and reuse
  T03's function instead.
- Timing-safe comparison (`secrets.compare_digest`) applies to both the bearer-token check and the
  HMAC verification in cookie verify — a naive `==` on either is a timing side-channel.
- The HMAC key is the resolved auth token itself (per design.md: "HMAC (keyed by the token)") — no
  new secret is generated or stored for this purpose.
- `session_ttl` (added to `WebApiConfig` by T01) is read at verify time, not baked into the cookie
  value itself (the cookie carries only the issuance timestamp; the TTL comparison happens against
  current config at verify time, so changing `session_ttl` takes effect for future verifications
  without needing to re-mint existing cookies).

## Verify

- [ ] FR#6: Unit test confirms a bearer-token check against the correct token succeeds and against an incorrect token fails, using `secrets.compare_digest` (not `==` — inspect the implementation).
- [ ] FR#7: Unit test confirms a cookie minted for a given token can be verified successfully against that same token, and that minting/verifying does not depend on any server-side state (e.g., verify works correctly if called from a fresh process with no prior mint call in memory, given only the token and cookie value).
- [ ] FR#8: Unit test confirms a cookie whose embedded issuance timestamp exceeds `session_ttl` is rejected by the verify function, and one within the TTL is accepted.
- [ ] FR#20: Unit test confirms the Secure-flag decision function returns `True` only when the peer is trusted (per T03's matcher) AND `X-Forwarded-Proto` says `https`; returns `False` when the peer is untrusted regardless of the header value, and confirms it calls T03's matcher rather than a separate comparison.
- [ ] FR#22: Unit test confirms the renewal predicate returns `False` for a freshly minted cookie, `True` for one whose issuance timestamp is past half of `session_ttl`, and `False` again for one already past full `session_ttl` (that case is rejected by verify, not renewed).
- [ ] A `None` resolved token returns "not authenticated" from both the bearer check and the cookie verify, without raising — asserted directly, since the `TypeError` this prevents would surface as a 500 in T05's tests rather than as a failure here.
