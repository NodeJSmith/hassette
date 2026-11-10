# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: A write whose connection dropped during the send-buffer drain records `not_sent`

Status: open
Recorded: 2026-11-10 (3677)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/websocket_io.py
- src/hassette/api/api.py

Issue:
`send_json` raises `CommandNotSentError` for a `ConnectionError` raised while waiting for the send buffer to drain, after which the frame may already have gone out. The write's row then reads `not_sent` ("never reached Home Assistant") where `connection_lost` would be accurate. `CommandNotSentError` documents the same edge case.

Why deferred:
Rare (Home Assistant stops reading a full socket and the connection drops mid-drain), and the consequence is a mislabel, not lost data. Telling the drain case apart needs a new transport signal handled in both send paths.

Recommended follow-up:
If incident investigations find a `not_sent` row for a call that applied, have `send_json` report the drain-time failure separately and leave the entry registered so `fail_all` records `connection_lost`.

Acceptance criteria:
- A connection lost during the drain wait records `connection_lost`, and one lost before the frame is written still records `not_sent`.

## KI-002: A cancelled non-retried framework write waits for its late reply and logs it

Status: open
Recorded: 2026-11-10 (3677)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/websocket_io.py
- src/hassette/core/websocket_responses.py

Issue:
Every non-retried write's pending entry now stays on cancellation, recorded or not, so a cancelled framework-`Api` write keeps a background slot until its reply or the connection ends, and its reply logs "Late reply to abandoned ...". The user docs don't mention the log line.

Why deferred:
Intended (one rule replaced mark-timed-out and discard-on-cancel; see the ledger's build calls), bounded by the background-entry cap, and the log line is accurate.

Recommended follow-up:
If users ask what "Late reply to abandoned" means, add a line to the API methods docs.

Acceptance criteria:
- The docs explain the late-reply log line for writes whose caller stopped waiting.

## KI-003: A fire-and-forget call cancelled before its frame is written reads `pending` until the connection ends

Status: open
Recorded: 2026-11-10 (3677)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/websocket_io.py

Issue:
`send_fire_and_forget` keeps the entry on `CancelledError`. If the cancel lands before any bytes are written, Home Assistant never saw the call, yet its row stays `pending` for the connection's lifetime and then reads `connection_lost`, holding a background slot meanwhile.

Why deferred:
D1 ratified this: a cancel during the socket write isn't told apart from one after it, as no peer does. The window is narrow and bounded by the cap.

Recommended follow-up:
If long-lived `pending` rows confuse users, say in the database telemetry docs that a `pending` row can last until its connection ends.

Acceptance criteria:
- The docs say a `pending` row can persist until its connection ends, or the transport tells a pre-write cancel apart and records `not_sent`.
