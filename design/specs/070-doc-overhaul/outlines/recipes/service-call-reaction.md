# Recipes — React to a Service Call

**Status:** Exists (32 lines), needs JTBD redesign — "How It Works" uses bullet lists with bold lead-ins (anti-pattern)
**Voice mode:** Recipe — problem statement uses "you", "How It Works" uses system-as-subject prose paragraphs
**Page type:** Recipe
**Reader's job:** Mirror or react to a Home Assistant service call — for example, sync settings from one light to another whenever someone adjusts the primary.

## What was cut

The existing "How It Works" uses a bullet-list format. Content stays, format
changes to flowing prose paragraphs.

Missing a "Verify It's Working" section. Adding one.

## Outline

### H2: (Problem statement)
You have a primary light and an accent light. Whenever someone adjusts the
primary through HA, the accent should mirror the brightness and color
temperature automatically.

### H2: The Code
Full app via `--8<--` include of `service_call_reaction.py`.

### H2: How It Works
Flowing prose paragraphs, one decision each:

1. Subscription scope — `on_call_service(domain="light", service="turn_on")`
   subscribes only to `light.turn_on` calls. No other service types reach the
   handler.
2. Predicate narrowing — `P.ServiceDataWhere({"entity_id": ...})` filters
   further so the handler fires only when the call targets the configured
   primary light.
3. Event payload — `CallServiceEvent.payload.data.service_data` is the dict of
   arguments the caller passed. The handler forwards whichever parameters were
   present (brightness, color_temp, transition) to the accent light, skipping
   keys not in the original call.
4. Config — `primary_light` and `accent_light` are environment-backed fields,
   changeable without touching code.

### H2: Verify It's Working
Adjust the primary light via the HA UI, then:
`hassette log --app <key> --since 5m` to see the handler fire.
`hassette listener --app <key>` to confirm the service-call handler is
registered.

### H2: Variations
- Watch any entity in a group: glob pattern in `ServiceDataWhere` (snippet:
  `service_call_where.py:where`).
- React to turn-off too: second subscription for `service="turn_off"`.

### H2: See Also
Links to Bus/Filtering (on_call_service, predicates), Bus overview.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `service_call_reaction.py` | Keep | Main app |
| `service_call_where.py` | Keep | Glob pattern variation |

## Cross-Links

- **Links to:** Bus/Filtering (on_call_service, P.ServiceDataWhere, P.ServiceMatches), Bus overview
- **Linked from:** Recipes overview
