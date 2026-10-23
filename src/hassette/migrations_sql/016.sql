-- Migration 016: partial index for the default log view.
--
-- With no author filter, log queries keep app lines plus framework lines at ERROR and above, newest
-- first, under a LIMIT (SQL_DEFAULT_LOG_VIEW in hassette/core/telemetry/helpers.py). Walking
-- idx_lr_time to fill that LIMIT reads every framework DEBUG/INFO line newer than the last app line,
-- which approaches a full scan of the retention window when app lines are sparse. This index holds
-- only the rows the default view shows, in its sort order.
--
-- SQLite uses a partial index only when the query's WHERE contains this exact predicate, so the
-- WHERE below must stay identical to SQL_DEFAULT_LOG_VIEW (literal levels, same term order).
CREATE INDEX idx_lr_default_view ON log_records(timestamp, seq)
    WHERE author = 'app' OR level IN ('ERROR', 'CRITICAL');
