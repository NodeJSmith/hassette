# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: A flagged instance whose name left the config loses its Handlers and Jobs rows

**Status:** open
**Reason:** accepted-limitation
**Recorded:** branch 3099, ship-time challenge

`DatabaseRetentionMixin.live_instances` counts an instance as present only when it is configured or running, and a flagged instance is unregistered. So renaming or removing a block whose teardown hung retires its listener and job rows, at the reload, while its leftover work may still run. The old name stays FAILED with its reason, an ERROR was logged, and retiring deletes nothing.

**Follow-up:** if this ever misleads a hung-teardown investigation, add flagged `(app_key, name)` pairs to `live_instances`.

## KI-002: `App.index` can go stale after an add or remove, not only a reorder

**Status:** open
**Reason:** accepted-limitation
**Recorded:** branch 3099, ship-time challenge

D3 keeps `App.index` frozen at construction and reasons about reorders. D2 also stops restarting siblings on a count change, so removing an instance can leave a sibling's `App.index` past its display index, and a later add can give two live apps the same value. On `main` before #3100, a status event built by `HassetteAppStateEvent.from_app` can then land on the wrong row, or share a frontend status key with a sibling, until the next refetch. No release shows this while #3099 and #3100 ship together.

**Follow-up:** #3100 keys live status on the name and decides whether `App.index` survives. If #3100 slips past the next release, send `resolved.index` from `RuntimeQueryService.on_app_state_changed`.
