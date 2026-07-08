# Prereq 06: Entity platforms end-to-end (v0.1 completion)

**Repos:** hass-hassette + hassette · **Blocked by:** prereq-04, prereq-05

Everything that makes v0.1 shippable: the six platforms working end-to-end with the full
lifecycle matrix from `research.md`.

## Scope

- Platforms in `hass-hassette`: `sensor`, `binary_sensor`, `switch`, `button`, `number`,
  `select`. Dynamic creation via dispatcher signals to pre-forwarded platforms;
  `RestoreEntity`; device per app instance with `via_device` → instance hub.
- `hassette/entity/register` (batch upsert), `hassette/entity/update` (batch state/
  attributes/availability), `hassette/entity/remove`, `hassette/sync` orphan sweep.
- Command platforms push `entity_command` envelopes over the subscription;
  confirmed-by-default (no optimistic flip unless `assumed_state`).
- Lifecycle verification against the research.md matrix: connection drop → unavailable;
  HA restart → restored-but-unavailable until reconnect; app reload → unavailable then
  re-registered; dropped entity → removed by sync.
- **System test:** install `hass-hassette` into hassette's system-test HA container and the
  demo stack; end-to-end test register → registry entry → command → handler → confirmed
  state. This is the real safety net for the whole epic.
- Docs both sides: HACS install guide (custom repo), entity API page, admin-token
  requirement, recorder-exclusion note.

## Files

- add `custom_components/hassette/{sensor,binary_sensor,switch,button,number,select}.py` and
  `entity.py` (base entity + dispatcher wiring) in `hass-hassette`
- extend `custom_components/hassette/websocket.py` (register/update/remove/sync commands)
- modify hassette system-test + demo-stack HA container setup to mount `hass-hassette`
- add system test covering the register → command → confirmed-state loop
