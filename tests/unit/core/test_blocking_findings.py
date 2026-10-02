"""Tests for grouping blocking_events rows into findings and the diagnostics summary."""

from pathlib import PurePath
from typing import Any

import pytest
from hassette_wire import StackFrame

from hassette.core.telemetry.blocking_findings import (
    RECENT_UNATTRIBUTED_LIMIT,
    classifier_for_apps,
    group_findings,
    summarize_unattributed,
)
from hassette.utils.stack_frames import FrameClassifier, encode_frames

APP_DIR = "/apps"
SSL = StackFrame(filename="/usr/local/lib/python3.13/ssl.py", lineno=1, function="read", module="ssl")
GCSA = StackFrame(
    filename="/venv/lib/python3.13/site-packages/gcsa/events.py", lineno=5, function="get_events", module="gcsa.events"
)
CAL = StackFrame(filename="/apps/calendar_service.py", lineno=98, function="get_calendar_events", module="cal")
HANDLER_A = StackFrame(filename="/apps/car_climate.py", lineno=10, function="scan_and_schedule", module="cc")
HANDLER_B = StackFrame(filename="/apps/car_climate.py", lineno=20, function="on_event_ending", module="cc")


def classifier_for(_: str | None) -> FrameClassifier:
    return FrameClassifier(app_dirs=(PurePath(APP_DIR),), excluded_dirs=(PurePath("/venv"), PurePath("/usr/local")))


def row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "app_key": "car_climate",
        "tier": "watchdog",
        "primitive": None,
        "stall_duration_ms": 100.0,
        "detected_ts": 1000.0,
        "reason": "attributed",
        "frames": None,
        "listener_id": None,
        "listener_name": None,
        "listener_method": None,
        "job_id": None,
        "job_name": None,
        "job_method": None,
    }
    frames = overrides.pop("stack", None)
    if frames is not None:
        base["frames"] = encode_frames(frames)
    return {**base, **overrides}


def listener(listener_id: int, name: str) -> dict[str, Any]:
    return {"listener_id": listener_id, "listener_name": name, "listener_method": name}


def job(job_id: int, name: str) -> dict[str, Any]:
    return {"job_id": job_id, "job_name": name, "job_method": name}


class TestGrouping:
    def test_one_finding_per_call_site_listing_every_handler(self) -> None:
        """Two handlers reaching the same helper line produce one finding naming both."""
        rows = [
            row(stack=[SSL, GCSA, CAL, HANDLER_A], detected_ts=3000.0, stall_duration_ms=534.0, **job(7, "scan")),
            row(stack=[SSL, GCSA, CAL, HANDLER_B], detected_ts=2000.0, stall_duration_ms=100.0, **listener(3, "end")),
            row(stack=[SSL, GCSA, CAL, HANDLER_A], detected_ts=1000.0, stall_duration_ms=200.0, **job(7, "scan")),
        ]

        [finding] = group_findings(rows, classifier_for)

        assert finding.call_site is not None
        assert (finding.call_site.display_path, finding.call_site.lineno) == ("calendar_service.py", 98)
        assert finding.call_site_is_user_code
        assert finding.callee is not None
        assert finding.callee.function == "get_events"
        assert finding.callee.display_path == "gcsa/events.py"
        assert [(h.kind, h.id) for h in finding.handlers] == [("job", 7), ("listener", 3)]
        assert finding.event_count == 3
        assert finding.max_stall_ms == pytest.approx(534.0)
        assert finding.avg_stall_ms == pytest.approx((534.0 + 100.0 + 200.0) / 3)
        assert finding.last_seen_ts == 3000.0
        assert finding.latest_stack == [SSL, GCSA, CAL, HANDLER_A]

    def test_different_call_sites_are_separate_findings_newest_first(self) -> None:
        rows = [row(stack=[HANDLER_B], detected_ts=2000.0), row(stack=[CAL, HANDLER_A], detected_ts=1000.0)]

        findings = group_findings(rows, classifier_for)

        assert [f.call_site.lineno for f in findings if f.call_site] == [20, 98]

    def test_same_call_site_in_different_apps_is_not_merged(self) -> None:
        rows = [row(stack=[CAL]), row(stack=[CAL], app_key="other_app")]
        assert {f.app_key for f in group_findings(rows, classifier_for)} == {"car_climate", "other_app"}

    def test_call_site_frame_with_nothing_inside_has_no_callee(self) -> None:
        [finding] = group_findings([row(stack=[CAL, HANDLER_A])], classifier_for)
        assert finding.callee is None


class TestCallSiteNotCaptured:
    def test_rows_without_frames_group_per_handler(self) -> None:
        """No stack (or a pre-structured-frames row) → one finding per handler, call_site None."""
        rows = [row(**listener(1, "a")), row(**listener(1, "a")), row(**job(2, "b")), row()]

        findings = group_findings(rows, classifier_for)

        assert all(f.call_site is None for f in findings)
        assert [([(h.kind, h.id) for h in f.handlers], f.event_count) for f in findings] == [
            ([("listener", 1)], 2),
            ([("job", 2)], 1),
            ([], 1),
        ]

    def test_stack_with_no_user_frame_is_not_captured(self) -> None:
        [finding] = group_findings([row(stack=[SSL, GCSA], **listener(1, "a"))], classifier_for)
        assert finding.call_site is None
        assert finding.latest_stack == [SSL, GCSA]

    def test_tiers_and_primitives_stay_separate(self) -> None:
        """Same handler, no call site: Tier 1 and each Tier 2 primitive are separate findings."""
        rows = [
            row(stall_duration_ms=300.0, **listener(1, "a")),
            row(tier="monkeypatch", primitive="time.sleep", stall_duration_ms=None, **listener(1, "a")),
            row(tier="monkeypatch", primitive="open", stall_duration_ms=None, **listener(1, "a")),
        ]

        findings = group_findings(rows, classifier_for)

        assert sorted((f.tier, f.primitive, f.event_count) for f in findings) == [
            ("monkeypatch", "open", 1),
            ("monkeypatch", "time.sleep", 1),
            ("watchdog", None, 1),
        ]
        [watchdog] = [f for f in findings if f.tier == "watchdog"]
        assert watchdog.max_stall_ms == 300.0


class TestTier2:
    def test_user_call_site_groups_by_primitive_and_location(self) -> None:
        rows = [
            row(tier="monkeypatch", primitive="time.sleep", stall_duration_ms=None, stack=[CAL]),
            row(tier="monkeypatch", primitive="time.sleep", stall_duration_ms=None, stack=[CAL]),
            row(tier="monkeypatch", primitive="builtins.open", stall_duration_ms=None, stack=[CAL]),
        ]

        findings = group_findings(rows, classifier_for)

        assert [(f.primitive, f.event_count) for f in findings] == [("time.sleep", 2), ("builtins.open", 1)]
        assert all(f.call_site_is_user_code and f.detected_in_package is None for f in findings)
        assert all(f.max_stall_ms is None and f.avg_stall_ms is None for f in findings)

    def test_library_call_site_names_the_package_instead(self) -> None:
        [finding] = group_findings(
            [row(tier="monkeypatch", primitive="socket.connect", stall_duration_ms=None, stack=[GCSA])], classifier_for
        )
        assert not finding.call_site_is_user_code
        assert finding.detected_in_package == "gcsa"


class TestUnattributed:
    def test_counts_reasons_and_shows_app_frame_as_evidence(self) -> None:
        rows = [
            row(app_key=None, reason="displaced", stall_duration_ms=5000.0, stack=[SSL, CAL]),
            row(app_key=None, reason="framework", stall_duration_ms=120.0, stack=[SSL]),
            row(app_key=None, reason=None, stall_duration_ms=None, tier="monkeypatch", primitive="time.sleep"),
        ]

        summary = summarize_unattributed(rows, classifier_for(None), truncated=True)

        assert (summary.total_count, summary.displaced_count, summary.framework_count) == (3, 1, 2)
        assert summary.max_stall_ms == pytest.approx(5000.0)
        assert summary.truncated
        assert [s.reason for s in summary.recent] == ["displaced", "framework", "framework"]
        assert summary.recent[0].app_frame is not None
        assert summary.recent[0].app_frame.display_path == "calendar_service.py"
        assert summary.recent[1].app_frame is None

    def test_recent_list_is_capped(self) -> None:
        rows = [row(app_key=None, reason="framework") for _ in range(RECENT_UNATTRIBUTED_LIMIT + 5)]
        summary = summarize_unattributed(rows, classifier_for(None), truncated=False)
        assert summary.total_count == RECENT_UNATTRIBUTED_LIMIT + 5
        assert len(summary.recent) == RECENT_UNATTRIBUTED_LIMIT


class TestClassifierForApps:
    def test_each_app_uses_its_own_dir_and_unknown_apps_use_all(self) -> None:
        lookup = classifier_for_apps({"a": PurePath("/apps/a"), "b": PurePath("/apps/b")})
        assert lookup("a").app_dirs == (PurePath("/apps/a"),)
        assert set(lookup("removed_app").app_dirs) == {PurePath("/apps/a"), PurePath("/apps/b")}
        assert set(lookup(None).app_dirs) == {PurePath("/apps/a"), PurePath("/apps/b")}
