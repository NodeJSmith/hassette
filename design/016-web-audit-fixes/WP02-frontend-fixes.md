# WP02: Frontend Fixes

**Lane:** todo
**Estimated scope:** 4 fixes across 4 frontend TypeScript files

## Changes

### 1. Extend ListenerData to match backend (#394)

**Files:**
- `frontend/src/api/endpoints.ts` — Add missing fields to `ListenerData` interface: `di_failures`, `cancelled`, `min_duration_ms`, `max_duration_ms`, `total_duration_ms`, `predicate_description`, `human_description`, `debounce`, `throttle`, `once`, `priority`, `last_error_message`, `last_error_type`, `source_location`, `registration_source`

**Test:** TypeScript compilation verifies the interface is valid.

### 2. Parse backend error detail in API client (#397)

**Files:**
- `frontend/src/api/client.ts` — Before throwing `ApiError`, attempt to read the response body as JSON and extract the `detail` field. Pass it as the message parameter to `ApiError`.

**Test:** Add unit test in a new `frontend/src/api/client.test.ts` that mocks `fetch` to return a non-2xx response with `{"detail": "specific error"}` and verifies `ApiError.message` contains the detail.

### 3. Replace LogTable .reverse() with actual .sort() (#403)

**Files:**
- `frontend/src/components/shared/log-table.tsx:68` — Replace:
  ```typescript
  const sorted = sortAsc.value ? [...filtered] : [...filtered].reverse();
  ```
  With:
  ```typescript
  const sorted = [...filtered].sort((a, b) =>
    sortAsc.value ? a.timestamp - b.timestamp : b.timestamp - a.timestamp
  );
  ```

**Test:**
- In `log-table.test.tsx`: add test with non-chronological timestamps (e.g., push 2000, 1000, 3000) and verify sort produces correct order
- Replace `describe.todo` with actual REST+WS merge test: override `getRecentLogs` mock to return entries, push WS entries, verify combined view

### 4. Add concurrency guard to ActionButtons exec (#404)

**Files:**
- `frontend/src/components/apps/action-buttons.tsx:15` — Add `if (loading.value) return;` as the first line of `exec`

**Test:**
- In `action-buttons.test.tsx`: add test that clicks Start twice rapidly and asserts `startApp` was called exactly once

## Acceptance criteria

- [ ] `ListenerData` interface has all fields from `ListenerWithSummary`
- [ ] API errors show backend detail messages (not just HTTP status text)
- [ ] LogTable sorts by timestamp (not insertion order)
- [ ] LogTable sort works with non-chronological entry order
- [ ] Double-click on action buttons fires API call exactly once
- [ ] All frontend tests pass
