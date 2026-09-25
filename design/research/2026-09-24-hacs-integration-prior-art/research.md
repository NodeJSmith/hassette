---
topic: "HACS / Home Assistant custom integration best practices and antipatterns, applied to hass-hassette"
date: 2026-09-24
status: Draft
---

# Prior Art: HACS / HA Custom Integration Practices for hass-hassette

> **Note (2026-09-24):** written while the design still used ADR-0004's inbound transport. The
> follow-up verification (HA connects out in every comparable core integration; `websocket_api`
> commands are frontend-facing) led to ADR-0006 (proposed). Patterns 3–4 (pending futures, blocking
> services) no longer apply to v0.1; the quality-scale idioms, pinning, HACS, and v0.2 findings still do.

## The Problem

hass-hassette will be a companion HACS integration for an external automation framework: it
registers custom `hassette/*` websocket commands, holds connection-scoped subscriptions, exposes
framework services that block on a reply from hassette (v0.1), and later creates dynamic entities
and devices (v0.2). HA custom integrations have a well-known failure record — breakage on monthly
HA releases, dependency conflicts, registry orphans, patterns that were idiomatic in 2021 and are
now flagged by the Integration Quality Scale. The goal is to build on current idioms rather than
copy an older reference implementation's conventions.

## How We Do It Today

Nothing is built. The design lives in `design/specs/113-hacs-companion-integration/brief.md`
(post-challenge), ADR-0004, and the July/August research. Its named reference implementation is
hass-node-red, which predates several current HA idioms.

## Patterns Found

### Pattern 1: Manifest-flag single-instance config entry

**Used by**: HA core's flow manager (any integration with `"single_config_entry": true`).
**How it works**: The `manifest.json` flag makes the flow manager abort a second entry with
`single_instance_allowed` before any integration code runs, so a zero-config `config_flow.py` is
just `async_step_user` → `async_create_entry(data={})`. hass-node-red instead hand-rolls
`_async_current_entries()` plus a redundant `hass.data` check (the legacy idiom).
**Strengths**: No boilerplate, can't be forgotten, consistent abort reason.
**Weaknesses**: Needs a new enough HA; the `hacs.json` minimum-HA version must be at or above the
release that introduced it.
**Example**: https://github.com/home-assistant/core/blob/dev/homeassistant/config_entries.py ·
https://developers.home-assistant.io/docs/config_entries_config_flow_handler/

### Pattern 2: Connection-scoped subscriptions via `connection.subscriptions[msg_id]`

**Used by**: HA's own websocket_api subscriptions; hass-node-red (webhooks, device triggers, version handshake).
**How it works**: Decorator order is `@require_admin` → `@websocket_command({schema})` →
`@async_response` (only on handlers that await). A subscribe handler stores a zero-argument
**synchronous** cleanup callable at `connection.subscriptions[msg["id"]]`; HA invokes it on
unsubscribe or disconnect. Pushes go out as `connection.send_message(event_message(id, {...}))`.
**Strengths**: Framework-owned disconnect detection, no polling; exactly ADR-0004's liveness mechanism.
**Weaknesses**: The cleanup can't `await`, so anything needing I/O has to be scheduled via
`hass.async_create_task` from inside it (for example, failing pending calls or marking entities
unavailable).
**Example**: https://github.com/zachowj/hass-node-red/blob/main/custom_components/nodered/websocket.py

### Pattern 3: Connection-scoped pending futures (request/response over a push channel)

**Used by**: aioesphomeapi (client side of the ESPHome native API). **No HA-core server-side
integration was found that pushes out and then blocks a service call on an external client's
reply.**
**How it works**: One `asyncio.Future` per call, tracked on the connection object. A timeout
handle fails it with `TimeoutError`. A `finally` block always deregisters it. Connection
teardown fails every still-pending future exactly once (`if not fut.done()`). Success, timeout,
cancellation, and disconnect all reach the same cleanup path.
**Strengths**: Can't leak or double-resolve; per-connection scope means a reconnect can't
cross-talk with earlier calls. Matches the brief's connection-scoped pending-call decision.
**Weaknesses**: Hand-rolled; HA has no helper for it.
**Example**: https://github.com/esphome/aioesphomeapi/blob/main/aioesphomeapi/connection.py
(`send_messages_await_response_complex`, `_cleanup`)

### Pattern 4: Fire-and-forget service + companion event (the precedent the brief diverges from)

**Used by**: HA's own actionable mobile notifications.
**How it works**: The service returns once the push is sent. The external reply arrives as an HA
event, and an automation that wants to block uses `wait_for_trigger` on a correlation id.
**Strengths**: No pending state in the integration at all.
**Weaknesses**: Every blocking caller hand-writes `wait_for_trigger` YAML; there's no typed error
in the automation trace and no `SupportsResponse` data.
**Example**: https://companion.home-assistant.io/docs/notifications/actionable-notifications/

### Pattern 5: Service registration and exceptions per the Quality Scale

**Used by**: Current core integrations (Bronze/Silver rules).
**How it works**: Services are registered in `async_setup`, not `async_setup_entry` (`action-setup`),
so automation validation works even when the entry isn't loaded. Handlers raise on failure
(`action-exceptions`): `ServiceValidationError` when the caller is at fault, `HomeAssistantError`
when the action failed. Both carry `translation_domain`/`translation_key`, with messages in
`strings.json` under `"exceptions"` (`exception-translations`). Runtime state lives in
`entry.runtime_data`, not `hass.data[DOMAIN]` (`runtime-data`).
**Strengths**: Translated, typed errors in automation traces; clean unload/reload.
**Weaknesses**: A little more ceremony than bare strings.
**Example**: https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/ ·
https://github.com/home-assistant/developers.home-assistant/blob/master/docs/dev_101_services.md

### Pattern 6: Coordinator-diff sync for dynamic devices and entities (v0.2)

**Used by**: HA's `dynamic-devices` / `stale-devices` quality-scale guidance.
**How it works**: Keep the authoritative set of upstream objects and diff it against the
previous set on each update. Additions get `async_add_entities`. Removals call
`async_remove_device` **only when certain** the object is gone, with
`async_remove_config_entry_device` as a manual UI-delete fallback. Listeners are registered via
`entry.async_on_unload`. A newer option, `RestoreDataUpdateCoordinator` (core PR #173318),
restores a whole coordinator payload from one `Store` instead of per-entity `RestoreEntity`.
**Strengths**: Idempotent; add and remove come from one diff; no leaked listeners.
**Weaknesses**: You must be able to tell "gone" apart from "temporarily unreachable". A hassette
disconnect is not an app deletion.
**Example**: https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/stale-devices/ ·
https://github.com/home-assistant/core/pull/173318

## Anti-Patterns

- **Copying hass-node-red's older conventions**: `hass.data[DOMAIN]` state, a hand-rolled
  single-instance check, and (by extension) services registered per entry. All three are now
  flagged by Bronze-tier quality-scale rules.
- **Exact-pinning anything HA ships or constrains.** #173019 (smartbox exact-pinned pydantic and
  failed to install on 2026.6) is the canonical incident. hassfest PR #181913 is formalizing
  rejection of `==` pins on HA-shipped packages for custom integrations. This applies
  transitively: `hassette-protocol`'s own `pyproject.toml` must not exact-pin anything HA ships.
  https://github.com/home-assistant/core/issues/173019 · https://github.com/home-assistant/core/pull/181913
- **Bare-string exceptions** instead of `translation_key` exceptions (`exception-translations`).
- **`hacs.json` `homeassistant` minimum drifting from the code's real API floor.** It either
  blocks valid installs or, since HACS enforcement has gaps, lets broken ones through (#4243).
  Needs a release-checklist or CI step.
- **Removing devices just because they're unreachable** (stale-devices warning). This matters
  for v0.2's sweep.
- **Platform bugs outside your control**: requirements that install but won't import on HAOS
  2026.4+ (core #171055), and a `RestoreEntity` timing regression in 2026.3 (#164802). Worth a
  troubleshooting doc entry, not code.

## Relevance to Us

The brief already matches best practice on the load-bearing decisions. ADR-0004's transport is
the hass-node-red subscription pattern. Connection-scoped pending calls match aioesphomeapi's
proven shape. Range-pinning `hassette-protocol` with the handshake as the skew guard is where
hassfest is heading. v0.1's no-devices scope avoids the whole registry-lifecycle risk surface.

Where the brief needs adjusting or making explicit:

1. **Services register in `async_setup`**, not per entry. When the entry isn't loaded, or
   hassette isn't connected, they raise (per finding 5's bounded wait) rather than disappearing.
2. **Error taxonomy → exception class + `translation_key`**: `not_found` / `blocked_by_filter` →
   `ServiceValidationError`; `not_bootstrapped` / `outcome_unknown` / `failed` →
   `HomeAssistantError`.
3. **`single_config_entry: true`** in the manifest, not a hand-rolled check; **`entry.runtime_data`**
   for hub and connection state.
4. **The subscription cleanup is synchronous**: failing pending calls happens inside it (setting
   exceptions on futures is sync, so that's fine), and anything async gets scheduled.
5. **Conscious divergence**: HA core has no precedent for a service blocking on an external
   client's reply; HA's own analog (actionable notifications) deliberately doesn't block. The
   brief's choice is defensible (typed errors, response data, no YAML boilerplate), but it's
   novel in HA terms. Keep the wait bounded (it is) and document it.
6. **Resolved open questions**: the HACS brands check is satisfied by an in-repo
   `custom_components/hassette/brand/icon.png` (since the Feb 2026 HACS change). Use
   `zip_release: true` + `filename` in `hacs.json`, with real GitHub Releases.
7. **Testing**: `pytest-homeassistant-custom-component` versions are tied to HA core releases, so
   its version must move with the HA pin. Its Syrupy snapshot extension suits v0.2 entity state.
   hass-node-red's CI (tests + lint + issue hygiene, no beta matrix) is a reasonable baseline.
8. **v0.2**: prefer the coordinator-diff shape (fed by the WS subscription) over ad hoc
   dispatcher bookkeeping, and evaluate `RestoreDataUpdateCoordinator` against per-entity
   `RestoreEntity`.

## Recommendation

Adopt Patterns 1, 2, 3, and 5 for Spec 1 as written above, fold points 1–6 of "Relevance to Us"
into the brief, and carry Pattern 6 into the v0.2 spec. Keep the blocking-service design, but
record it as a deliberate divergence from HA's actionable-notification precedent.

**Coverage gaps:** no dedicated source for the dispatcher-signal entity pattern (v0.2 concern). The
minimum HA version for `single_config_entry` wasn't confirmed. hass-node-red's CI workflow
contents weren't read (the beta-testing question is unanswered). URLs were not live-verified.

## Sources

### Reference implementations
- https://github.com/zachowj/hass-node-red/blob/main/custom_components/nodered/websocket.py — WS command decorators, subscriptions, cleanup
- https://github.com/zachowj/hass-node-red/blob/main/custom_components/nodered/__init__.py — setup/unload shape
- https://github.com/zachowj/hass-node-red/blob/main/custom_components/nodered/config_flow.py — legacy single-instance zero-config flow
- https://github.com/zachowj/hass-node-red/tree/main/.github/workflows — companion-integration CI baseline
- https://github.com/esphome/aioesphomeapi/blob/main/aioesphomeapi/connection.py — pending-future / timeout / teardown pattern
- https://github.com/home-assistant/core/blob/dev/homeassistant/config_entries.py — `single_config_entry` enforcement
- https://github.com/home-assistant/core/pull/181913 — hassfest rule against exact pins on HA-shipped packages
- https://github.com/home-assistant/core/pull/173318 — `RestoreDataUpdateCoordinator`
- https://github.com/MatthewFlamm/pytest-homeassistant-custom-component — test harness, HA version coupling

### Issues & incidents
- https://github.com/home-assistant/core/issues/173019 — exact-pin pydantic install failure
- https://github.com/home-assistant/core/issues/171055 — requirements install but fail to import (HAOS 2026.4+)
- https://github.com/darthrater78/HA-Stock-App/issues/52, https://github.com/kristofdegrave/homeassistant-smart-charging/issues/1031 — `hacs.json` min-version drift

### Documentation & standards
- https://developers.home-assistant.io/docs/config_entries_config_flow_handler/
- https://developers.home-assistant.io/docs/frontend/extending/websocket-api/
- https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/ (action-setup, action-exceptions, exception-translations, runtime-data, unique-config-entry, dynamic-devices, stale-devices)
- https://github.com/home-assistant/developers.home-assistant/blob/master/docs/dev_101_services.md
- https://developers.home-assistant.io/blog/2022/07/10/entity_naming/ — `has_entity_name`
- https://developers.home-assistant.io/docs/creating_integration_manifest/
- https://www.hacs.xyz/docs/publish/integration/ — repo layout, brands, releases
- https://companion.home-assistant.io/docs/notifications/actionable-notifications/ — non-blocking precedent
- https://developers.home-assistant.io/blog/ — deprecation channel
