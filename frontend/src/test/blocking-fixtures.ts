/** Factories for event-loop blocking findings and unattributed stalls. */

import type { components } from "../api/generated-types";
import { FIXED_TEST_TIMESTAMP } from "./factories";

type BlockingFinding = components["schemas"]["BlockingFinding"];
type BlockingFrameRef = components["schemas"]["BlockingFrameRef"];
type UnattributedStall = components["schemas"]["UnattributedStall"];

export function createFrameRef(overrides: Partial<BlockingFrameRef> = {}): BlockingFrameRef {
  return {
    filename: "/apps/calendar_service.py",
    lineno: 98,
    function: "get_calendar_events",
    module: "calendar_service",
    display_path: "calendar_service.py",
    ...overrides,
  } satisfies BlockingFrameRef;
}

export function createBlockingFinding(overrides: Partial<BlockingFinding> = {}): BlockingFinding {
  return {
    app_key: "test_app",
    tier: "watchdog",
    call_site: createFrameRef(),
    call_site_is_user_code: true,
    detected_in_package: null,
    callee: createFrameRef({
      filename: "/venv/lib/python3.13/site-packages/gcsa/events.py",
      lineno: 5,
      function: "get_events",
      module: "gcsa.events",
      display_path: "gcsa/events.py",
    }),
    primitive: null,
    handlers: [
      { kind: "job", id: 7, name: "scan_and_schedule", handler_method: "scan_and_schedule", instance_index: 0 },
    ],
    instances: [{ index: 0, name: "CarClimate.0" }],
    event_count: 9,
    max_stall_ms: 534,
    avg_stall_ms: 300,
    last_seen_ts: FIXED_TEST_TIMESTAMP,
    latest_stack: [
      { filename: "/usr/local/lib/python3.13/ssl.py", lineno: 1, function: "read", module: "ssl" },
      { filename: "/apps/calendar_service.py", lineno: 98, function: "get_calendar_events", module: "cal" },
    ],
    ...overrides,
  } satisfies BlockingFinding;
}

export function createUnattributedStall(overrides: Partial<UnattributedStall> = {}): UnattributedStall {
  return {
    detected_ts: FIXED_TEST_TIMESTAMP,
    tier: "watchdog",
    reason: "displaced",
    stall_duration_ms: 5000,
    primitive: null,
    app_frame: null,
    stack: [],
    ...overrides,
  } satisfies UnattributedStall;
}
