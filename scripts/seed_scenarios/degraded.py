"""The ``degraded`` scenario: 5 apps in the warning band between healthy and critical."""

# dup-ignore-file: per-app scenario blocks repeat the same seed-helper call shape by design
# -- see the package docstring in __init__.py.

from hassette.types.types import ExecutionStatus
from seed_scenarios.base import (
    APP_TIME_SPACING_SECONDS,
    HEARTBEAT_OFFSET_SECONDS,
    STATE_CHANGED_TOPIC,
    SeedContext,
    make_execution_id,
    seed_app_blocking_event,
    seed_executions,
    seed_job,
    seed_listener,
    seed_log_records,
    seed_simple_app,
    ts,
)
from tests.support.factories import make_execution_record


def scenario_degraded(ctx: SeedContext) -> None:
    """Mixed health: 2 apps healthy, 2 apps in the "warning" band, 1 app with boot issues.

    Health-threshold margin note: ``classify_health_bar`` (telemetry_helpers.py) treats
    success_rate in [90, 95) as "warning". The two elevated-error apps below target a 7.5%
    error rate (92.5% success) — solidly centered in that band, 2.5 points from each boundary.
    """
    seq = 1

    for i, (app_key, class_name, n_errors) in enumerate(
        [("weather_watcher", "WeatherWatcher", 0), ("garage_door", "GarageDoor", 0)]
    ):
        base = i * APP_TIME_SPACING_SECONDS
        ctx.add_app_manifest(app_key=app_key, class_name=class_name)
        seed_simple_app(
            ctx,
            scenario="degraded",
            app_key=app_key,
            class_name=class_name,
            base_offset=base,
            exec_count=20,
            n_errors=n_errors,
        )
        seq = seed_log_records(
            ctx,
            start_seq=seq,
            count=2,
            app_key=app_key,
            class_name=class_name,
            base_offset=base,
        )

    # leaky_faucet_monitor and hallway_thermostat are seeded individually (not in a loop) so
    # hallway_thermostat's session_id is captured directly, for the blocking event below.
    base = 2 * APP_TIME_SPACING_SECONDS
    ctx.add_app_manifest(app_key="leaky_faucet_monitor", class_name="LeakyFaucetMonitor")
    seed_simple_app(
        ctx,
        scenario="degraded",
        app_key="leaky_faucet_monitor",
        class_name="LeakyFaucetMonitor",
        base_offset=base,
        exec_count=40,
        n_errors=3,
    )
    seq = seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key="leaky_faucet_monitor",
        class_name="LeakyFaucetMonitor",
        base_offset=base,
        level="ERROR",
        message_prefix="Repeated connection failures",
    )

    hallway_base = 3 * APP_TIME_SPACING_SECONDS
    ctx.add_app_manifest(app_key="hallway_thermostat", class_name="HallwayThermostat")
    hallway_session_id, _listener_id, _job_id = seed_simple_app(
        ctx,
        scenario="degraded",
        app_key="hallway_thermostat",
        class_name="HallwayThermostat",
        base_offset=hallway_base,
        exec_count=40,
        n_errors=3,
    )
    seq = seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key="hallway_thermostat",
        class_name="HallwayThermostat",
        base_offset=hallway_base,
        level="ERROR",
        message_prefix="Repeated connection failures",
    )

    # Boot-issue app: first boot fails outright, second boot recovers to 'running'.
    app_key, class_name = "boiler_controller", "BoilerController"
    base = 4 * APP_TIME_SPACING_SECONDS
    ctx.add_app_manifest(app_key=app_key, class_name=class_name)
    failed_session_id = ctx.add_session(
        started_at=ts(base),
        last_heartbeat_at=ts(base + 5.0),
        stopped_at=ts(base + 5.0),
        status="failure",
        error_type="ConnectionError",
        error_message="Could not reach Home Assistant",
    )
    running_session_id = ctx.add_session(
        started_at=ts(base + 60.0), last_heartbeat_at=ts(base + HEARTBEAT_OFFSET_SECONDS)
    )
    listener_id = seed_listener(
        ctx,
        app_key=app_key,
        handler_method=f"{class_name}.on_temperature_change",
        topic=STATE_CHANGED_TOPIC,
        name=f"{app_key}_temp_listener",
        source_location=f"{app_key}.py:20",
    )
    job_id = seed_job(
        ctx,
        app_key=app_key,
        job_name=f"{app_key}_recalibrate",
        handler_method=f"{class_name}.recalibrate",
        trigger_type="interval",
        trigger_label="every 30 minutes",
        source_location=f"{app_key}.py:30",
    )
    # DI failure during the failed boot attempt — the dependency never came up in time.
    ctx.add_execution(
        make_execution_record(
            kind="handler",
            execution_id=make_execution_id("degraded", app_key, 0),
            session_id=failed_session_id,
            listener_id=listener_id,
            app_key=app_key,
            status=ExecutionStatus.ERROR,
            execution_start_ts=ts(base + 2.0),
            duration_ms=15.0,
            error_type="DependencyError",
            error_message="Api dependency not ready",
            is_di_failure=True,
        )
    )
    seed_executions(
        ctx,
        scenario="degraded",
        app_key=app_key,
        session_id=running_session_id,
        listener_id=listener_id,
        count=6,
        n_errors=1,
        start_index=1,
        base_offset=base + 120.0,
    )
    seed_executions(
        ctx,
        scenario="degraded",
        app_key=app_key,
        session_id=running_session_id,
        kind="job",
        job_id=job_id,
        count=4,
        start_index=7,
        base_offset=base + 400.0,
    )
    seq = seed_log_records(
        ctx,
        start_seq=seq,
        count=1,
        app_key=app_key,
        class_name=class_name,
        base_offset=base + 1.0,
        level="ERROR",
        message_prefix="Failed to connect to Home Assistant on boot",
    )

    seed_app_blocking_event(
        ctx,
        session_id=hallway_session_id,
        app_key="hallway_thermostat",
        class_name="HallwayThermostat",
        detected_ts=ts(hallway_base + 500.0),
        stall_duration_ms=1800.0,
    )
