-- Migration 015: log_records.source_tier -> author.
--
-- Log lines now record who wrote them (`author`: 'app' or 'framework'), not the owner tier every other
-- telemetry table keeps in `source_tier`. The insert always names `author`, so the 'framework' default
-- only exists because SQLite needs one to add a NOT NULL column; production writes never reach it.
--
-- Existing rows get an author derived from logger_name and the row's instance_name. This is a one-time
-- legacy derivation for rows written before the field existed, NOT a reusable author rule: the live
-- rule is LogIdentityFilter in hassette/logging_.py, which reads the identity fixed on the writing
-- logger. An app's own logger name ends in its instance name in every released naming scheme
-- (`hassette.apps.<instance>`, and `hassette.<Class>.<instance>` before that), while its framework
-- children (Bus, Scheduler, Api, Lifecycle) nest one level deeper and end in a class name. Loggers
-- outside the `hassette` namespace are the user's own module loggers.
--
-- Both tests (the `hassette` namespace prefix and the `.<instance_name>` suffix) are exact and
-- case-sensitive on purpose. LIKE and GLOB are not: LIKE ignores case and
-- treats `_` and `%` as wildcards, so it would match child `hassette.apps.api.Api` for instance `api`.
--
-- Known misreads, left to age out with log retention:
--   - captured warnings (`py.warnings`) read 'app'
--   - a user's `self.logger.getChild(...)` logger reads 'framework'
--   - an instance named like a child class, or like the last part of a framework module logger,
--     reads those lines as 'app'
--   - an app line stored without instance_name reads 'framework'
--
-- One-way: source_tier is dropped, so rolling back past 015 means deleting the telemetry database.
-- log_records has no index or view on source_tier, so the column drops in place.
ALTER TABLE log_records ADD COLUMN author TEXT NOT NULL DEFAULT 'framework'
    CHECK (author IN ('app', 'framework'));

UPDATE log_records
SET author = 'app'
-- Outside the namespace, or ending in '.<instance_name>'. A NULL instance_name makes the suffix test
-- NULL, so such in-namespace rows keep the 'framework' default.
WHERE NOT (logger_name = 'hassette' OR substr(logger_name, 1, 9) = 'hassette.')
   OR substr(logger_name, -(length(instance_name) + 1)) = '.' || instance_name;

ALTER TABLE log_records DROP COLUMN source_tier;
