---
task_id: "T02"
title: "Move AnnotationDetails and identity to di/, update dependencies.py"
status: "planned"
depends_on: ["T01"]
implements: ["FR#8", "FR#9", "AC#5"]
---

## Summary
Remove `AnnotationDetails` and `identity` definitions from `event_handling/dependencies.py` and replace them with imports from `hassette.di`. All `D.*` type aliases remain in `dependencies.py` and continue to construct `AnnotationDetails(...)` — the only change is where `AnnotationDetails` and `identity` are defined. No backward-compatibility re-export is maintained; `hassette.di` is the canonical path.

## Target Files
- modify: `src/hassette/event_handling/dependencies.py`
- read: `src/hassette/di/types.py`

## Prompt
Edit `src/hassette/event_handling/dependencies.py` to:

1. Remove the `AnnotationDetails` class definition (lines 85-93) and the `identity` function definition (lines 118-123).
2. Remove the `T` TypeVar definition at line 81 (`T = TypeVar("T", bound=Event[Any])`) — it's no longer needed here since `AnnotationDetails` is defined in `di/types.py` with its own unbounded `T`.
3. Add imports: `from hassette.di import AnnotationDetails, identity`
4. Keep the `R` TypeVar (line 83) — it's used by `ensure_present`.
5. Keep everything else unchanged: `ensure_present`, all `D.*` aliases (`TypedStateChangeEvent`, `StateNew`, `MaybeStateNew`, `StateOld`, `MaybeStateOld`, `EntityId`, `MaybeEntityId`, `Domain`, `MaybeDomain`, `EventContext`, `EventData`), the `EventDataT` TypeVar, and the accessor imports.

The `D.*` aliases construct `AnnotationDetails(...)` with extractors — these calls must still work with the imported class. Since `AnnotationDetails` is now unbounded on `T` (was `bound=Event[Any]`), the aliases that parameterize it with event types (e.g., `AnnotationDetails["RawStateChangeEvent"]`) will still work — the bound was removed, not narrowed.

Reference: design doc FR#8, FR#9, AC#5.

## Focus
- The `D.*` aliases use `AnnotationDetails` both as a type (`Annotated[..., AnnotationDetails[...]]`) and as a constructor (`AnnotationDetails(extractor=...)`). Both usages must work after the import.
- `identity` is used directly in the `TypedStateChangeEvent` alias at line 132: `AnnotationDetails["RawStateChangeEvent"](identity)`.
- The `Event` import at line 69 (`from hassette.events import Event`) is still needed for the `HassContext` import and event type references in the aliases. Do not remove it.
- The `T` TypeVar is ONLY used by `AnnotationDetails` in this file — safe to remove. But `R = TypeVar("R")` at line 83 is used by `ensure_present` — keep it.
- The `MISSING_VALUE` and `FalseySentinel` imports (line 68) are used by the `MaybeEntityId` and `MaybeDomain` aliases — keep them.
- Check that Pyright shows no new errors after this change — the widened `T` bound should only accept more, not less.

## Verify
- [ ] FR#8: `AnnotationDetails` definition removed from `dependencies.py`, imported from `hassette.di`; `T` TypeVar removed; `source_type` field available on imported class
- [ ] FR#9: `identity` definition removed from `dependencies.py`, imported from `hassette.di`
- [ ] AC#5: `D.*` type aliases in `dependencies.py` import `AnnotationDetails` from `hassette.di`
