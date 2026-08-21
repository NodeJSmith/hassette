# Context: Status Exhaustiveness Enforcement

## Problem & Motivation

PR #1605 introduced `ManifestStatus.DEGRADED` and post-merge review found 5 frontend locations that silently ignored it. Three active bugs remain: degraded apps missing from the failure alert, skipped executions mislabeled as "completed", and skipped executions missing a badge. The root cause is that all status-mapping functions accept `string` instead of the generated literal union types, preventing any compile-time exhaustiveness enforcement.

## Key Decisions

1. Convert `Map<string, X>` dispatch tables in `status.ts` to `Record<Union, X>` with `satisfies` — this is the pattern already proven by `ConnectionStatus` in the codebase
2. Import literal union types from `generated-types.ts` (`ManifestStatus`, `ResourceStatus`, `ExecutionStatus`) rather than hand-rolling them
3. Define a combined `StatusMapKey` union for `APP_STATUS_MAP` that includes both enums plus service-health values (`"success"`, `"failure"`, `"unknown"`) and the legacy frontend-only `"shutting_down"` (not in either backend enum)
4. Delete the hand-rolled `AppStatus` type in `status.ts` — it's superseded by the generated types
5. Convert `executionStatusKind` from an if/else chain to a `Record<ExecutionStatus, StatusKind>` lookup
6. Narrow upstream interfaces (`AppStatusEntry.status/previous_status`, `ServiceStatusEntry.status/previous_status`, `appLiveStatus()`/`instanceLiveStatus()` return types) so caller sites compile without casts
7. Fix WS schema Pydantic models (`domain_models.py`, `web/models.py`) to use proper enum types instead of `str`
8. Keep `levelToVariant`/`levelToKind` as `string` — log levels are open-ended
5. Keep `levelToVariant`/`levelToKind` as `string` — log levels are open-ended
6. File issues for WS connectivity, StateCacheFreshness, and app-in-service-status gaps rather than bundling them

## Constraints

- Backend Python changes are limited to fixing type widening in the WS schema export layer (`domain_models.py`, `web/models.py`) — not adding match/assert_never to consumers
- Do NOT fix WS connectivity refresh, StateCacheFreshness observability, or app-in-service-status leak — those are separate issues
- Do NOT convert `levelToVariant`/`levelToKind` from `string` — log levels are open-ended
- All existing frontend tests must continue to pass after retyping
- Do NOT use `as` casts to resolve type mismatches — narrow the source interface instead
