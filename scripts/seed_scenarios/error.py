"""The ``error`` scenario: 5 apps failing hard, with crashed sessions and error logs."""

# dup-ignore-file: per-app scenario blocks repeat the same seed-helper call shape by design
# -- see the package docstring in __init__.py.

from seed_scenarios.base import (
    APP_TIME_SPACING_SECONDS,
    STATE_CHANGED_TOPIC,
    SeedContext,
    make_instance_name,
    seed_app_blocking_event,
    seed_executions,
    seed_job,
    seed_listener,
    seed_log_records,
    ts,
)


def scenario_error(ctx: SeedContext) -> None:
    """5 fictional apps all failing hard: 85% error rates (success rate 15% — comfortably
    past the <90% "critical" boundary), crashed and boot-failed sessions, a thread-leaked
    execution, error/critical log records, and one blocking event per app.
    """
    apps = [
        ("smoke_alarm_bridge", "SmokeAlarmBridge"),
        ("leak_detector", "LeakDetector"),
        ("irrigation_controller", "IrrigationController"),
        ("camera_relay", "CameraRelay"),
        ("door_lock_sync", "DoorLockSync"),
    ]
    seq = 1
    for i, (app_key, class_name) in enumerate(apps):
        base = i * APP_TIME_SPACING_SECONDS
        ctx.add_app_manifest(app_key=app_key, class_name=class_name)
        if i == 0:
            # Boot failure followed by a crash on the retry -- the worst-case narrative.
            ctx.add_session(
                started_at=ts(base),
                last_heartbeat_at=ts(base + 5.0),
                stopped_at=ts(base + 5.0),
                status="failure",
                error_type="ConnectionError",
                error_message="Could not reach Home Assistant",
            )
            session_id = ctx.add_session(
                started_at=ts(base + 30.0),
                last_heartbeat_at=ts(base + 90.0),
                stopped_at=ts(base + 90.0),
                status="crashed",
                error_type="RuntimeError",
                error_message="Unhandled exception in bus dispatch",
                error_traceback=(
                    "Traceback (most recent call last):\n  ...\nRuntimeError: Unhandled exception in bus dispatch"
                ),
            )
        else:
            session_id = ctx.add_session(
                started_at=ts(base),
                last_heartbeat_at=ts(base + 90.0),
                stopped_at=ts(base + 90.0),
                status="crashed",
                error_type="RuntimeError",
                error_message=f"{class_name} crashed during startup",
                error_traceback=(
                    f"Traceback (most recent call last):\n  ...\nRuntimeError: {class_name} crashed during startup"
                ),
            )

        listener_id = seed_listener(
            ctx,
            app_key=app_key,
            handler_method=f"{class_name}.on_state_change",
            topic=STATE_CHANGED_TOPIC,
            name=f"{app_key}_state_listener",
            source_location=f"{app_key}.py:10",
        )
        job_id = seed_job(
            ctx,
            app_key=app_key,
            job_name=f"{app_key}_health_check",
            handler_method=f"{class_name}.health_check",
            trigger_type="interval",
            trigger_label="every 5 minutes",
            source_location=f"{app_key}.py:25",
        )

        # 20 executions total (15 handler + 5 job), 17 errors (85%) -- deep in "critical".
        seed_executions(
            ctx,
            scenario="error",
            app_key=app_key,
            session_id=session_id,
            listener_id=listener_id,
            count=15,
            n_errors=13,
            n_thread_leaked=(1 if i == 1 else 0),
            base_offset=base + 100.0,
            error_message=f"{class_name} handler failed",
        )
        seed_executions(
            ctx,
            scenario="error",
            app_key=app_key,
            session_id=session_id,
            kind="job",
            job_id=job_id,
            count=5,
            n_errors=4,
            start_index=15,
            base_offset=base + 2000.0,
            error_message=f"{class_name} job failed",
        )

        seq = seed_log_records(
            ctx,
            start_seq=seq,
            count=3,
            app_key=app_key,
            class_name=class_name,
            base_offset=base,
            level="ERROR",
            message_prefix=f"{class_name} handler error",
        )
        ctx.add_log_record(
            seq=seq,
            timestamp=ts(base + 95.0),
            level="CRITICAL",
            logger_name=f"hassette.apps.{app_key}",
            message=f"{class_name} session crashed",
            app_key=app_key,
            instance_name=make_instance_name(class_name, 0),
            instance_index=0,
            source_tier="app",
        )
        seq += 1

        seed_app_blocking_event(
            ctx,
            session_id=session_id,
            app_key=app_key,
            class_name=class_name,
            detected_ts=ts(base + 50.0),
            stall_duration_ms=3000.0,
        )
