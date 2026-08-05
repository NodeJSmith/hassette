---
task_id: "T01"
title: "Extract shared loopback classifier to utils/net_utils.py"
status: "planned"
depends_on: []
implements: ["FR#9", "AC#8"]
---

## Summary

Move `_is_loopback_host` out of `core/web_api_service.py` into a new `utils/net_utils.py` so the CLI and the server share one loopback classifier. Both feed the same trust decision — the server uses it to decide whether an unauthenticated bind is acceptable, and the CLI will use it to decide whether a credential may be sent. Two independently-written versions can silently disagree about `::ffff:127.0.0.1`, which is a security bug rather than a style nit. This is a pure move plus tests; no behavior changes.

## Target Files

- create: `src/hassette/utils/net_utils.py`
- create: `tests/unit/utils/test_net_utils.py`
- modify: `src/hassette/core/web_api_service.py`
- modify: `src/hassette/web/auth.py`
- read: `design/specs/092-cli-remote-url/design.md`
- read: `design/specs/092-cli-remote-url/tasks/context.md`

## Prompt

Create `src/hassette/utils/net_utils.py` containing a public `is_loopback_host(host: str) -> bool` moved verbatim (modulo the name and the leading underscore) from `_is_loopback_host` at `src/hassette/core/web_api_service.py:45-58`, along with the `_LOOPBACK_HOSTNAMES` frozenset at line 41. Keep the existing implementation exactly: `ipaddress.ip_address(host).is_loopback` inside a `try`, falling back to `host.lower() in _LOOPBACK_HOSTNAMES` on `ValueError`. Do not add DNS resolution. Preserve and adapt the existing docstring, which already explains why hostnames are handled separately rather than resolved.

Then update `src/hassette/core/web_api_service.py`: import `is_loopback_host` from `hassette.utils.net_utils`, update the single call site at line 100 (`loopback = _is_loopback_host(web_api_config.host)`), and delete both the local `_is_loopback_host` function and the `_LOOPBACK_HOSTNAMES` constant. No local definition may remain — this is a move, not a copy.

`src/hassette/web/auth.py:71` contains a docstring that cross-references `` `core/web_api_service.py`'s `_is_loopback_host` `` as an example of the duplicate-rather-than-cycle tradeoff. That reference goes stale with this move. Update it to point at `utils/net_utils.py`'s `is_loopback_host`, and adjust the surrounding sentence so it no longer cites this function as an instance of accepted duplication — it is now the shared one.

Add `tests/unit/utils/test_net_utils.py` covering the classification table in AC#8. Create the `tests/unit/utils/` directory only if it does not already exist (it does — `tests/unit/utils/test_await_guard.py` is there).

See `## Architecture → Credential scoping` and `## Key Constraints` in the design doc for why this is shared rather than reimplemented.

## Focus

`_is_loopback_host` currently has exactly one call site (`web_api_service.py:100`), so the move is low-risk. Verify with `grep -rn "_is_loopback_host" src/ tests/` after the change — the only remaining matches should be the updated `web/auth.py` docstring reference (now naming the new location) and nothing in `core/`.

`utils/` sits below `events/` in the layer DAG enforced by `tools/check_module_boundaries.py`, so importing it from both `core/` and `cli/` is legal. Do not import `core.web_api_service` from `cli/` instead — that is what this move exists to avoid.

Behavior worth knowing while writing the tests: `ipaddress.ip_address("::ffff:127.0.0.1").is_loopback` is `True` (IPv4-mapped form), `ipaddress.ip_address("127.0.0.53").is_loopback` is `True` (systemd-resolved's stub, inside `127.0.0.0/8`), and `ipaddress.ip_address("0.0.0.0").is_loopback` is `False`. The hostname fallback is case-insensitive via `.lower()`, so `LOCALHOST` classifies as loopback.

Bracketed IPv6 (`[::1]`) does not reach this function in bracketed form from the CLI — `yarl.URL.host` returns the unbracketed spelling. Test the unbracketed form here; T03 owns the bracket-stripping path.

## Verify

- [ ] FR#9: `is_loopback_host` in `src/hassette/utils/net_utils.py` classifies by parsing the host as an IP literal and reporting `is_loopback`, falling back to a fixed hostname set, with no DNS call anywhere in the function; `grep -rn "_is_loopback_host" src/hassette/core/` returns no match.
- [ ] AC#8: `uv run pytest tests/unit/utils/test_net_utils.py -v` passes with assertions that `localhost`, `LOCALHOST`, `127.0.0.1`, `127.0.0.53`, `::1`, and `::ffff:127.0.0.1` classify as loopback while `192.168.1.5`, `example.com`, and `0.0.0.0` do not.
