---
task_id: "T03"
title: "Add trusted_proxies IP/CIDR/hostname matching to web/auth.py"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#2", "FR#3", "AC#4"]
---

## Summary

Extends `src/hassette/web/auth.py` with the trusted-proxy peer-matching mechanism: parses
`trusted_proxies` entries as IPs, CIDRs, or hostnames, resolves hostnames via DNS, and exposes a
function that checks whether a given peer address is currently trusted. This is the "no credential
needed" fast path for operators running a forward-auth gateway. Only the raw ASGI `scope["client"]`
is ever compared — this task builds the matcher as a pure function that only accepts an address
string, never a headers dict, so header-spoofing isn't even representable at this layer.

## Target Files

- modify: `src/hassette/web/auth.py` — add trusted-proxy matching functions
- modify: `tests/unit/web/test_auth.py` — unit tests for matching (created by T02)
- read: `src/hassette/config/models.py` — `WebApiConfig.trusted_proxies` field (added by T01)

## Prompt

Read design.md's `## Architecture → Credential model` (first paragraph) and FR#2, FR#3, plus the
Edge Cases "trusted_proxies DNS resolution failure" and "A trusted_proxies entry that's wrong or too
broad."

In `src/hassette/web/auth.py`, add:

1. **Config-load-time parsing** of each `trusted_proxies` entry: IP and CIDR literals parse via the
   stdlib `ipaddress` module (`ipaddress.ip_address()` / `ipaddress.ip_network()`), failing loudly on
   a malformed entry (per the Edge Case: this is a real footgun — an auth *bypass*, not an additive
   check — so a typo'd CIDR like `0.0.0.0/0` should be rejected or at minimum the config validator
   should make it very hard to get there silently; if full "obviously wrong entry" detection is
   ambiguous to implement generically, at minimum ensure malformed IP/CIDR/hostname syntax raises
   immediately rather than being silently ignored).
2. **Hostname resolution**: for entries that aren't valid IP/CIDR literals, resolve via
   `socket.getaddrinfo()`. A resolution failure at this stage fails loudly (same posture as an
   invalid IP/CIDR literal) — this task builds the resolve function; T08 wires it into startup and a
   periodic `Scheduler.run_every()` refresh, so failure-handling here should be a function that
   raises or returns clearly on failure, letting the caller (T08) decide retry/refresh semantics.
3. **A peer-match function** — e.g. `is_trusted_peer(client_address: str, trusted_set: <resolved
   addresses/networks>) -> bool` — that takes only an address string (never a request object, never a
   headers mapping) and checks it against the currently-resolved set of trusted IPs/CIDRs/hostname
   resolutions. This function's signature is itself the FR#3 guarantee: there is no way to pass
   header data into it.
4. **A refresh function** that re-resolves all hostname entries and returns (or updates) the current
   trusted address set, for T08 to call both at startup and periodically. On a transient resolution
   failure during refresh (not the first resolution), keep the last-known-good resolved address
   rather than dropping trust immediately (per the Edge Case) — write the refresh function so it
   merges/preserves rather than replaces-with-empty on a partial failure.

Write unit tests in `tests/unit/web/test_auth.py` (created by T02) covering: a plain IP entry
matches only that IP; a CIDR entry matches any address in range; a hostname entry resolves and
matches the resolved IP; calling the refresh function with a changed DNS response updates which
addresses are trusted (this is the "simulated periodic-refresh tick" the design's AC#5 describes —
mock `socket.getaddrinfo` to return different results on two successive calls and confirm the trusted
set changes accordingly); a malformed IP/CIDR entry raises at parse time.

## Focus

- **FR#3 is structural, not just behavioral** — the peer-match function must not accept a headers
  argument at all. A reviewer checking this design's single most consequential control (per Key
  Constraints) will look at the function signature first.
- Do not implement the actual `Scheduler.run_every()` wiring here — that's T08. This task provides
  the resolve/refresh functions as pure logic; T08 imports and schedules them.
- The "simulated periodic-refresh tick" test described in design.md's AC#5 is satisfiable here at the
  unit level by calling the refresh function twice with different mocked `socket.getaddrinfo`
  results — it does not require the real `Scheduler` or `WebApiService` to be running. Full app-level
  AC#5 verification (an actual request through the middleware landing as trusted after a hostname's
  IP changes) happens in T11's integration suite, which depends on this task.
- Malformed-entry detection doesn't need to catch every conceivable "too broad" CIDR (e.g. detecting
  `0.0.0.0/0` specifically as "too broad" is a judgment call, not a syntax error) — the concrete,
  testable requirement is that syntactically invalid entries fail loudly at parse time. Don't build
  a heuristic "is this CIDR suspiciously broad" checker; that's speculative validation beyond what
  FR#2/FR#3 ask for.

## Verify

- [ ] FR#2: Unit test confirms a peer address matching a `trusted_proxies` IP, CIDR, or resolved-hostname entry is reported as trusted by the matcher function.
- [ ] FR#3: The peer-match function's signature accepts only an address string (verified by inspection/type signature — no headers parameter exists); unit test confirms passing a non-matching address with no other input still returns not-trusted (there is no header input to spoof).
- [ ] AC#4: Unit test confirms a peer address matching a `trusted_proxies` IP or CIDR entry is trusted by the matcher, and a non-matching address is not.
