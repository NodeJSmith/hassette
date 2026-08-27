"""Shared app-key, timestamp, and id constants for e2e mock fixtures."""

# App keys for the seeded apps. Every fixture module keys its per-app data off these, so a
# rename lands in one place instead of across the manifest, telemetry, and scheduler seeds.
APP_KEY_MY_APP = "my_app"
APP_KEY_OTHER_APP = "other_app"
APP_KEY_BROKEN_APP = "broken_app"
APP_KEY_DISABLED_APP = "disabled_app"
APP_KEY_NOSOURCE_APP = "nosource_app"
APP_KEY_MULTI_APP = "multi_app"

TS_BASE = 1_704_067_200.0
TS_RECENT = 1_704_067_100.0
TS_OLDER = 1_704_067_050.0
TS_OLDEST = 1_704_067_000.0

# Start/stop timestamps for the two finished sessions on the sessions page. Session 1 is still
# running, so it uses TS_BASE as its start and has no stop.
TS_SESSION_2_STARTED = 1_704_060_000.0
TS_SESSION_2_STOPPED = 1_704_063_600.0
TS_SESSION_3_STARTED = 1_704_050_000.0
TS_SESSION_3_STOPPED = 1_704_053_600.0

# duration_seconds reported for every seeded session, running or finished.
SESSION_DURATION_SECONDS = 3600.0

# job_id of the manual-only job seeded so it's discoverable and submittable through the live
# UI. Shared between the DB telemetry row and the trigger stub.
MANUAL_JOB_ID = 4
