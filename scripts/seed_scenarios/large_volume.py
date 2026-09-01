"""The ``large-volume`` scenario: high row counts for pagination and performance checks."""

from seed_scenarios.base import (
    APP_TIME_SPACING_SECONDS,
    SeedContext,
    seed_app_blocking_event,
    seed_executions,
    seed_log_records,
    seed_simple_app,
    ts,
)


def scenario_large_volume(ctx: SeedContext) -> None:
    """8-10 fictional apps producing 1000+ executions total, to exercise frontend pagination.

    Error rates vary per app for a mix of health statuses -- exact rates don't need the same
    over-seeded boundary margins the ``degraded`` and ``error`` scenarios use.
    """
    apps = [
        ("hvac_zone_a", "HvacZoneA", 0),
        ("hvac_zone_b", "HvacZoneB", 3),
        ("hvac_zone_c", "HvacZoneC", 8),
        ("hvac_zone_d", "HvacZoneD", 15),
        ("hvac_zone_e", "HvacZoneE", 25),
        ("hvac_zone_f", "HvacZoneF", 40),
        ("hvac_zone_g", "HvacZoneG", 60),
        ("hvac_zone_h", "HvacZoneH", 90),
        ("network_monitor", "NetworkMonitor", 5),
        ("backup_scheduler", "BackupScheduler", 20),
    ]
    exec_count = 120
    seq = 1
    session_ids_by_app: dict[str, int] = {}
    for i, (app_key, class_name, error_pct) in enumerate(apps):
        base = i * APP_TIME_SPACING_SECONDS
        ctx.add_app_manifest(app_key=app_key, class_name=class_name)
        session_id, listener_id, _job_id = seed_simple_app(
            ctx,
            scenario="large-volume",
            app_key=app_key,
            class_name=class_name,
            base_offset=base,
            exec_count=15,
        )
        session_ids_by_app[app_key] = session_id
        remaining = exec_count - 15
        n_errors = min(round(exec_count * error_pct / 100), remaining)
        seed_executions(
            ctx,
            scenario="large-volume",
            app_key=app_key,
            session_id=session_id,
            listener_id=listener_id,
            count=remaining,
            n_errors=n_errors,
            start_index=15,
            base_offset=base + 900.0,
            interval_seconds=30.0,
        )
        seq = seed_log_records(
            ctx,
            start_seq=seq,
            count=20,
            app_key=app_key,
            class_name=class_name,
            base_offset=base,
            interval_seconds=45.0,
        )

    seed_app_blocking_event(
        ctx,
        session_id=session_ids_by_app["hvac_zone_g"],
        app_key="hvac_zone_g",
        class_name="HvacZoneG",
        detected_ts=ts(6 * APP_TIME_SPACING_SECONDS + 500.0),
        stall_duration_ms=1500.0,
    )
