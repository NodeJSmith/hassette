"""The ``lifecycle`` scenario: retired, removed, and reregistered listeners and jobs."""

# dup-ignore-file: per-app scenario blocks repeat the same seed-helper call shape by design
# -- see the package docstring in __init__.py.

from seed_scenarios.base import (
    APP_TIME_SPACING_SECONDS,
    HEARTBEAT_OFFSET_SECONDS,
    STATE_CHANGED_TOPIC,
    SeedContext,
    add_running_session,
    seed_app_blocking_event,
    seed_executions,
    seed_job,
    seed_listener,
    seed_log_records,
    seed_simple_app,
    ts,
)


def scenario_lifecycle(ctx: SeedContext) -> None:
    """4 apps covering all four retired/cancelled combinations from the design doc's
    Lifecycle Field Contract, multi-session apps (crashed + restarted), and a multi-instance
    app (instance_index 0 and 1).
    """
    seq = 1

    # -- sprinkler_controller: one active listener, one retired-only listener --
    app_key, class_name = "sprinkler_controller", "SprinklerController"
    base = 0.0
    ctx.add_app_manifest(app_key=app_key, class_name=class_name)
    seed_simple_app(
        ctx,
        scenario="lifecycle",
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
        exec_count=10,
    )
    seed_listener(
        ctx,
        app_key=app_key,
        handler_method=f"{class_name}.on_legacy_trigger",
        topic="hass.event.legacy_trigger",
        name=f"{app_key}_legacy_listener",
        source_location=f"{app_key}.py:50",
        retired_at=ts(base + 7200.0),
    )
    seq = seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
    )

    # -- alarm_system: active listener, a cancelled-only job, crashed session then a restart --
    app_key, class_name = "alarm_system", "AlarmSystem"
    base = APP_TIME_SPACING_SECONDS
    ctx.add_app_manifest(app_key=app_key, class_name=class_name)
    ctx.add_session(
        started_at=ts(base),
        last_heartbeat_at=ts(base + 30.0),
        stopped_at=ts(base + 30.0),
        status="crashed",
        error_type="RuntimeError",
        error_message="Unhandled exception in event loop",
        error_traceback="Traceback (most recent call last):\n  ...\nRuntimeError: Unhandled exception in event loop",
    )
    running_session_id = ctx.add_session(
        started_at=ts(base + 90.0), last_heartbeat_at=ts(base + HEARTBEAT_OFFSET_SECONDS)
    )
    listener_id = seed_listener(
        ctx,
        app_key=app_key,
        handler_method=f"{class_name}.on_motion",
        topic=STATE_CHANGED_TOPIC,
        name=f"{app_key}_motion_listener",
        source_location=f"{app_key}.py:15",
    )
    seed_job(
        ctx,
        app_key=app_key,
        job_name=f"{app_key}_nightly_test",
        handler_method=f"{class_name}.nightly_test",
        trigger_type="cron",
        trigger_label="nightly at 02:00",
        source_location=f"{app_key}.py:40",
        removed_at=ts(base + 200.0),
    )
    seed_executions(
        ctx,
        scenario="lifecycle",
        app_key=app_key,
        session_id=running_session_id,
        listener_id=listener_id,
        count=8,
        base_offset=base + 100.0,
    )
    seq = seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
        level="ERROR",
        message_prefix="Recovered after crash",
    )

    # -- camera_array: multi-instance app; instance 1 has a retired+cancelled listener --
    app_key, class_name = "camera_array", "CameraArray"
    base = 2 * APP_TIME_SPACING_SECONDS
    ctx.add_app_manifest(app_key=app_key, class_name=class_name)
    session_id_0 = add_running_session(ctx, base)
    listener_id_0 = seed_listener(
        ctx,
        app_key=app_key,
        handler_method=f"{class_name}.on_motion",
        topic=STATE_CHANGED_TOPIC,
        name=f"{app_key}_motion_listener",
        source_location=f"{app_key}.py:18",
    )
    session_id_1 = add_running_session(ctx, base)
    listener_id_1 = seed_listener(
        ctx,
        app_key=app_key,
        instance_index=1,
        handler_method=f"{class_name}.on_motion",
        topic=STATE_CHANGED_TOPIC,
        name=f"{app_key}_motion_listener",
        source_location=f"{app_key}.py:18",
    )
    # removed during runtime, then retired on the next startup reconciliation -- both set.
    seed_listener(
        ctx,
        app_key=app_key,
        instance_index=1,
        handler_method=f"{class_name}.on_old_event",
        topic="hass.event.old_topic",
        name=f"{app_key}_old_listener",
        source_location=f"{app_key}.py:60",
        removed_at=ts(base + 1800.0),
        retired_at=ts(base + 3600.0),
    )
    seed_executions(
        ctx,
        scenario="lifecycle",
        app_key=app_key,
        session_id=session_id_0,
        listener_id=listener_id_0,
        count=6,
        base_offset=base,
    )
    # start_index=6 avoids an execution_id collision with instance 0's executions above --
    # both instances share the same app_key by design (that's the point of "multi-instance").
    seed_executions(
        ctx,
        scenario="lifecycle",
        app_key=app_key,
        session_id=session_id_1,
        listener_id=listener_id_1,
        count=6,
        start_index=6,
        base_offset=base + 400.0,
    )
    seq = seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
    )
    seq = seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key=app_key,
        class_name=class_name,
        instance_index=1,
        base_offset=base + 400.0,
    )

    # -- mail_notifier: normal app, carries the scenario's one blocking event --
    app_key, class_name = "mail_notifier", "MailNotifier"
    base = 3 * APP_TIME_SPACING_SECONDS
    ctx.add_app_manifest(app_key=app_key, class_name=class_name)
    session_id, _listener_id, _job_id = seed_simple_app(
        ctx,
        scenario="lifecycle",
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
        exec_count=8,
    )
    seq = seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
    )
    seed_app_blocking_event(
        ctx,
        session_id=session_id,
        app_key=app_key,
        class_name=class_name,
        detected_ts=ts(base + 500.0),
        stall_duration_ms=900.0,
    )
