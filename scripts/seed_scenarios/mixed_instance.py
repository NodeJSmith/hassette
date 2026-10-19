"""The ``mixed-instance`` scenario: one multi-instance app with a running and a failed instance.

This is the telemetry shape behind ``ManifestStatus.DEGRADED``. The
seeder writes telemetry only -- ``ManifestStatus`` is derived live by ``AppRegistry`` -- so
this scenario does not by itself make a live dashboard badge show ``DEGRADED``.
"""

# dup-ignore-file: per-instance scenario blocks repeat the same seed-helper call shape by design
# -- see the package docstring in __init__.py.

from seed_scenarios.base import (
    STATE_CHANGED_TOPIC,
    SeedContext,
    add_running_session,
    seed_executions,
    seed_job,
    seed_listener,
    seed_log_records,
)

FAILED_INSTANCE_OFFSET_SECONDS = 400.0


def scenario_mixed_instance(ctx: SeedContext) -> None:
    """One multi-instance app, ``split_brain``: instance 0 runs cleanly (successful
    executions, INFO logs) while instance 1 has failed (only error executions, ERROR logs).

    Instance attribution lives on the listener/job rows (``instance_index``); executions
    inherit it through their ``listener_id``/``job_id``. Both instances share one running
    session, since a session is the whole hassette process, not a single app instance.
    """
    app_key, class_name = "split_brain", "SplitBrain"
    ctx.add_app_manifest(app_key=app_key, class_name=class_name)
    session_id = add_running_session(ctx, 0.0)
    seq = 1

    # -- instance 0: healthy and running --
    listener_id_0 = seed_listener(
        ctx,
        app_key=app_key,
        handler_method=f"{class_name}.on_state_change",
        topic=STATE_CHANGED_TOPIC,
        name=f"{app_key}_state_listener",
        source_location=f"{app_key}.py:14",
    )
    job_id_0 = seed_job(
        ctx,
        app_key=app_key,
        job_name=f"{app_key}_sync",
        handler_method=f"{class_name}.sync",
        trigger_type="interval",
        trigger_label="every 10 minutes",
        source_location=f"{app_key}.py:30",
    )
    seed_executions(
        ctx,
        scenario="mixed-instance",
        app_key=app_key,
        session_id=session_id,
        listener_id=listener_id_0,
        count=6,
    )
    seed_executions(
        ctx,
        scenario="mixed-instance",
        app_key=app_key,
        session_id=session_id,
        kind="job",
        job_id=job_id_0,
        count=3,
        start_index=6,
    )
    seq = seed_log_records(
        ctx,
        start_seq=seq,
        count=3,
        app_key=app_key,
        class_name=class_name,
        base_offset=0.0,
    )

    # -- instance 1: failed, no successful execution --
    # start_index continues past instance 0's executions: both instances share the app_key,
    # so execution_id (built from scenario/app_key/index) would otherwise collide.
    listener_id_1 = seed_listener(
        ctx,
        app_key=app_key,
        instance_index=1,
        handler_method=f"{class_name}.on_state_change",
        topic=STATE_CHANGED_TOPIC,
        name=f"{app_key}_state_listener",
        source_location=f"{app_key}.py:14",
    )
    job_id_1 = seed_job(
        ctx,
        app_key=app_key,
        instance_index=1,
        job_name=f"{app_key}_sync",
        handler_method=f"{class_name}.sync",
        trigger_type="interval",
        trigger_label="every 10 minutes",
        source_location=f"{app_key}.py:30",
    )
    seed_executions(
        ctx,
        scenario="mixed-instance",
        app_key=app_key,
        session_id=session_id,
        listener_id=listener_id_1,
        count=4,
        n_errors=4,
        start_index=9,
        base_offset=FAILED_INSTANCE_OFFSET_SECONDS,
        error_type="ConnectionError",
        error_message=f"{class_name} instance 1 could not reach its upstream device",
    )
    seed_executions(
        ctx,
        scenario="mixed-instance",
        app_key=app_key,
        session_id=session_id,
        kind="job",
        job_id=job_id_1,
        count=2,
        n_errors=2,
        start_index=13,
        base_offset=FAILED_INSTANCE_OFFSET_SECONDS,
        error_type="ConnectionError",
        error_message=f"{class_name} instance 1 sync failed",
    )
    seed_log_records(
        ctx,
        start_seq=seq,
        count=3,
        app_key=app_key,
        class_name=class_name,
        instance_index=1,
        base_offset=FAILED_INSTANCE_OFFSET_SECONDS,
        level="ERROR",
        message_prefix=f"{class_name} instance 1 failed",
    )
