"""Shared timestamp and id constants for e2e mock fixtures."""

TS_BASE = 1_704_067_200.0
TS_RECENT = 1_704_067_100.0
TS_OLDER = 1_704_067_050.0
TS_OLDEST = 1_704_067_000.0

# job_id of the manual-only job seeded so it's discoverable and submittable through the live
# UI. Shared between the DB telemetry row and the trigger stub.
MANUAL_JOB_ID = 4
