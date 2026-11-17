# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: Union conversion errors repeat the value and list every arm

Status: open
Recorded: 2026-11-17 (4152)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/conversion/annotation_converter.py

Issue:
When every arm of a union annotation fails, `UnableToConvertValueError` carries the value in its own message and again inside each arm's error text, so a large payload appears two or three times in the `DependencyResolutionError`, the execution record and the log line. Scalar unions such as `int | float` also list every arm's error now, not only model unions.

Why deferred:
Cosmetic, and visible only when a large value fails a union-typed parameter repeatedly. D1 already accepted values in DI errors.

Recommended follow-up:
If stored error strings or log lines grow noticeably, drop the outer `{value!r}` when arm detail is present, or list arm errors only for model/dataclass arms.

Acceptance criteria:
- A failed union conversion names the value at most once.

## KI-002: Dispatch-failure log reads the event type from the raw frame

Status: open
Recorded: 2026-11-17 (4152)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/websocket_inbound.py
- src/hassette/events/hass/hass.py

Issue:
`log_dispatch_failure` reads `event_type` from the raw frame through `hass_event_type`, separately from `create_event_from_hass`, so two pieces of code read the envelope's shape.

Why deferred:
The frame read is needed for every dispatch failure type, not just `MissingPayloadFieldsError`, so carrying the event type on that error wouldn't remove the second reader.

Recommended follow-up:
If `create_event_from_hass`'s envelope handling changes, keep `hass_event_type` reading the same field, or move both onto one shared accessor.

Acceptance criteria:
- One function reads the event type from a frame for both event construction and failure logging.

## KI-003: `D.MessageData[T | None]` never receives None

Status: open
Recorded: 2026-11-17 (4152)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/event_handling/dependencies.py

Issue:
`MessageData` wraps its accessor in `ensure_present`, so a hand-fired `data: null` skips the handler even when the annotation includes `| None`. The `| None` arm only affects error reporting.

Why deferred:
It matches every required extractor (`EventData`, `StateNew`, `EntityId`), the failure is logged, and hass-hassette's `hassette.send` action never sends a null `data`.

Recommended follow-up:
If users write `D.MessageData[X | None]` expecting null delivery, add a note to the `MessageData` docstring, or a `MaybeMessageData` variant if there's demand.

Acceptance criteria:
- A user annotating `D.MessageData[X | None]` can tell from the docs what a null `data` does.

## KI-004: Docs state Hassette 0.65.0 as the message floor before that release exists

Status: open
Recorded: 2026-11-17 (4152)
Source: ship-challenge
Reason not fixed now: blocked
Affected files:
- docs/pages/getting-started/home-assistant-integration.md

Issue:
"Sending messages needs Hassette 0.65.0 or newer" assumes this PR ships in the next release. pyproject is at 0.64.0, and release-please cuts 0.65.0 only if no other release lands first. hass-hassette's README (other repo) states the same floor.

Why deferred:
The real number is known only when release-please opens the release PR that ships this change.

Recommended follow-up:
When curating that release PR, confirm the version; if it isn't 0.65.0, fix the sentence here and send hass-hassette a one-line README fix.

Acceptance criteria:
- Both the docs page and hass-hassette's README name the hassette release that first contains `on_hassette_message`.
