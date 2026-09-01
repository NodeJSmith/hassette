"""The ``adversarial`` scenario: hostile-but-valid data — long strings, Unicode, nulls, extremes."""

# dup-ignore-file: per-app scenario blocks repeat the same seed-helper call shape by design
# -- see the package docstring in __init__.py.

from seed_scenarios.base import (
    APP_TIME_SPACING_SECONDS,
    MONKEYPATCH_TIER,
    REASON_FRAMEWORK,
    STATE_CHANGED_TOPIC,
    SeedContext,
    add_running_session,
    seed_app_blocking_event,
    seed_executions,
    seed_job,
    seed_listener,
    seed_log_records,
    ts,
)


def scenario_adversarial(ctx: SeedContext) -> None:
    """3 fictional apps that stress UI rendering: 100+ character handler/topic strings, a
    100+ listener fan-out on one app, and Unicode identifiers -- plus DI failures, a
    thread-leaked execution, and both blocking-event tiers.
    """
    seq = 1

    # -- long_handler_names_app: 100+ character handler names, long nested-predicate topics --
    app_key, class_name = "long_handler_names_app", "LongHandlerNamesApp"
    base = 0.0
    ctx.add_app_manifest(app_key=app_key, class_name=class_name)
    session_id = add_running_session(ctx, base)
    long_handler = (
        f"{class_name}.on_extremely_verbose_state_change_handler_that_describes_"
        "exactly_what_it_does_in_the_method_name_itself_for_maximum_clarity_and_length"
    )
    long_topic = (
        "hass.event.state_changed.binary_sensor.upstairs_hallway_motion_sensor_near_"
        "the_guest_bedroom_door[state == 'on' and attributes.battery_level > 20 and not context.user_id]"
    )
    listener_id = seed_listener(
        ctx,
        app_key=app_key,
        handler_method=long_handler,
        topic=long_topic,
        name=f"{app_key}_verbose_listener",
        predicate_description=(
            "lambda e: e.payload.data.new_state.state == 'on' and "
            "e.payload.data.new_state.attributes.get('battery_level', 0) > 20"
        ),
        human_description="battery above 20% and state is on, nested three predicates deep",
        source_location=f"{app_key}.py:200",
    )
    seed_executions(
        ctx,
        scenario="adversarial",
        app_key=app_key,
        session_id=session_id,
        listener_id=listener_id,
        count=10,
        n_di_failures=1,
        n_thread_leaked=1,
        base_offset=base,
        error_type="DependencyError",
        error_message="Api dependency not ready during long-running handler",
    )
    seq = seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
    )

    # -- many_listeners_app: 120 listeners on one app --
    app_key, class_name = "many_listeners_app", "ManyListenersApp"
    base = APP_TIME_SPACING_SECONDS
    ctx.add_app_manifest(app_key=app_key, class_name=class_name)
    session_id = add_running_session(ctx, base)
    n_listeners = 120
    listener_ids = [
        seed_listener(
            ctx,
            app_key=app_key,
            handler_method=f"{class_name}.on_sensor_{i:03d}",
            topic=f"hass.event.state_changed.sensor.sensor_{i:03d}",
            name=f"{app_key}_listener_{i:03d}",
            source_location=f"{app_key}.py:{10 + i}",
        )
        for i in range(n_listeners)
    ]
    seed_executions(
        ctx,
        scenario="adversarial",
        app_key=app_key,
        session_id=session_id,
        listener_id=listener_ids[0],
        count=5,
        base_offset=base,
    )
    seq = seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
    )

    # -- Unicode app key, listener name, and job name (Japanese + emoji) --
    app_key, class_name = "モーションセンサー_\U0001f3e0", "MotionSensor"
    base = 2 * APP_TIME_SPACING_SECONDS
    # filename override: app_key is Unicode/emoji, not a valid filename on most filesystems.
    ctx.add_app_manifest(app_key=app_key, class_name=class_name, filename=f"{class_name}.py")
    session_id = add_running_session(ctx, base)
    listener_id = seed_listener(
        ctx,
        app_key=app_key,
        handler_method=f"{class_name}.on_motion_detected",
        topic=STATE_CHANGED_TOPIC,
        name="動作検知リスナー_\U0001f6b6",
        source_location=f"{class_name}.py:5",
    )
    job_id = seed_job(
        ctx,
        app_key=app_key,
        job_name="毎日の点検_☀️",
        handler_method=f"{class_name}.daily_check",
        trigger_type="cron",
        trigger_label="毎日午前6時",
        source_location=f"{class_name}.py:20",
    )
    seed_executions(
        ctx,
        scenario="adversarial",
        app_key=app_key,
        session_id=session_id,
        listener_id=listener_id,
        count=5,
        base_offset=base,
    )
    seed_executions(
        ctx,
        scenario="adversarial",
        app_key=app_key,
        session_id=session_id,
        kind="job",
        job_id=job_id,
        count=3,
        start_index=5,
        base_offset=base + 400.0,
    )
    seq = seed_log_records(
        ctx,
        start_seq=seq,
        count=2,
        app_key=app_key,
        class_name=class_name,
        base_offset=base,
        message_prefix="動作を検知しました",
    )

    # -- Blocking events: both tiers -- one attributed to the Unicode app, one unresolved --
    seed_app_blocking_event(
        ctx,
        session_id=session_id,
        app_key=app_key,
        class_name=class_name,
        detected_ts=ts(base + 500.0),
        stall_duration_ms=2500.0,
    )
    ctx.add_blocking_event(
        tier=MONKEYPATCH_TIER,
        reason=REASON_FRAMEWORK,
        session_id=None,
        app_key=None,
        instance_name=None,
        instance_index=None,
        primitive="time.sleep",
        source_location="hassette/core/executor.py:88",
        detected_ts=ts(base + 600.0),
        source_tier="framework",
        stall_duration_ms=None,
    )
