"""The ``healthy`` scenario: 5 apps running normally, well above the "good" health threshold."""

from seed_scenarios.base import (
    APP_TIME_SPACING_SECONDS,
    REASON_FRAMEWORK,
    WATCHDOG_TIER,
    SeedContext,
    seed_app_api_writes,
    seed_listener,
    seed_listener_misses,
    seed_log_records,
    seed_simple_app,
    ts,
)


def scenario_healthy(ctx: SeedContext) -> None:
    """5 fictional apps with normal activity and excellent/good health — no failures beyond
    an occasional handled error, comfortably above the 95% "good" success-rate threshold.

    A single minimal blocking event is included (see the comment below) so this scenario
    still populates all 8 telemetry tables without undermining the "healthy install" narrative.
    """
    # Two apps have no description, so the UI shows both the described and undescribed shape.
    apps = [
        ("weather_watcher", "WeatherWatcher", 0, "Announces rain in the forecast before the morning commute"),
        ("garage_door", "GarageDoor", 1, "Closes the garage door if it's left open after dark"),
        ("plant_monitor", "PlantMonitor", 0, None),
        ("media_controller", "MediaController", 1, "Pauses living room media when the doorbell rings"),
        ("pet_feeder", "PetFeeder", 0, None),
    ]
    seq = 1
    for i, (app_key, class_name, n_errors, description) in enumerate(apps):
        base = i * APP_TIME_SPACING_SECONDS
        ctx.add_app_manifest(app_key=app_key, class_name=class_name, description=description)
        session_id, listener_id, _ = seed_simple_app(
            ctx,
            scenario="healthy",
            app_key=app_key,
            class_name=class_name,
            base_offset=base,
            exec_count=20,
            n_errors=n_errors,
        )
        # A few writes per app, linked to its first handler runs; one app has a rejected call.
        seed_app_api_writes(
            ctx,
            scenario="healthy",
            app_key=app_key,
            class_name=class_name,
            session_id=session_id,
            base_offset=base,
            entity_id=f"light.{app_key}",
            count=3,
            n_rejected=1 if app_key == "garage_door" else 0,
        )
        # One app's state listener has an hour of near-misses, so `--misses` and its route have rows to show.
        if app_key == "plant_monitor":
            seed_listener_misses(
                ctx,
                listener_id=listener_id,
                base_offset=base,
                entity_id=f"sensor.{app_key}",
                filter_summary="→ on",
            )
        # Second listener per app, for the "2-3 listeners" spread called for in the design doc.
        seed_listener(
            ctx,
            app_key=app_key,
            handler_method=f"{class_name}.on_call_service",
            topic="hass.event.call_service",
            name=f"{app_key}_service_listener",
            source_location=f"{app_key}.py:24",
        )
        seq = seed_log_records(
            ctx,
            start_seq=seq,
            count=3,
            app_key=app_key,
            class_name=class_name,
            base_offset=base,
            message_prefix=f"{class_name} processed update",
        )

    # See docstring: populates the blocking_events table without affecting health scoring
    # (blocking events don't factor into compute_error_rate/classify_health_bar).
    ctx.add_blocking_event(
        tier=WATCHDOG_TIER,
        reason=REASON_FRAMEWORK,
        session_id=None,
        app_key=None,
        instance_name=None,
        detected_ts=ts(60.0),
        source_tier="framework",
        stall_duration_ms=120.0,
    )
