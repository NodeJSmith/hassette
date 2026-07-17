"""CLI entry point for sync facade generation."""

import argparse
import sys
from pathlib import Path

from hassette_codegen.output import atomic_write, format_via_ruff
from hassette_codegen.sync_facade.generic import (
    generate_sync,
    generate_sync_bus,
    generate_sync_helpers,
    generate_sync_scheduler,
)
from hassette_codegen.sync_facade.recording import generate_sync_recording

_REPO_ROOT = Path(__file__).resolve().parents[4]


_LABEL_TO_TARGET = {
    "ApiSyncFacade": "api",
    "RecordingSyncFacade": "recording",
    "BusSyncFacade": "bus",
    "SchedulerSyncFacade": "scheduler",
    "HelperClientSyncFacade": "helpers",
}
"""Maps a facade label to the ``--target`` value that regenerates it (for drift hints)."""


def _atomic_write_generated(out_path: Path, content: str) -> None:
    """Atomically write generated source — delegates to shared output.atomic_write.

    Raises SystemExit on py_compile failure (sync facade's original behavior).
    """
    if not atomic_write(out_path, content):
        raise SystemExit(f"Generated file failed validation (target: {out_path})")


def _check_drift(target_path: Path, generated_content: str, label: str) -> bool:
    """Check if target_path content matches generated_content after ruff normalization.

    Args:
        target_path: Path to the committed file.
        generated_content: Freshly generated content.
        label: Human-readable label for the error message (e.g. "ApiSyncFacade").

    Returns:
        True if in-sync, False if drift detected.

    """
    if not target_path.exists():
        target = _LABEL_TO_TARGET.get(label, "all")
        print(
            f"{label} is out of date (target file does not exist).\n"
            f"Re-run: uv run python codegen/src/hassette_codegen/sync_facade/ --target {target}",
            file=sys.stderr,
        )
        return False

    committed_content = target_path.read_text(encoding="utf-8")
    normalized_committed = format_via_ruff(committed_content)
    normalized_generated = format_via_ruff(generated_content)

    if normalized_committed == normalized_generated:
        return True

    target = _LABEL_TO_TARGET.get(label, "all")
    rerun_cmd = f"uv run python codegen/src/hassette_codegen/sync_facade/ --target {target}"

    print(
        f"{label} is out of date.\nRe-run: {rerun_cmd}",
        file=sys.stderr,
    )
    return False


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for generate_sync_facade.py."""
    parser = argparse.ArgumentParser(description="Generate sync facade(s) from api.py and recording_api.py")
    parser.add_argument(
        "--api-path",
        type=Path,
        default=_REPO_ROOT / "src" / "hassette" / "api" / "api.py",
        help="Path to api.py (default: hassette/api.py relative to repo root)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path for sync.py (default: alongside api.py as sync.py)",
    )
    parser.add_argument(
        "--recording-api-path",
        type=Path,
        default=_REPO_ROOT / "src" / "hassette" / "test_utils" / "recording_api.py",
        help="Path to recording_api.py (default: hassette/test_utils/recording_api.py)",
    )
    parser.add_argument(
        "--recording-out",
        type=Path,
        default=_REPO_ROOT / "src" / "hassette" / "test_utils" / "sync_facade.py",
        help="Output path for the generated recording sync facade",
    )
    parser.add_argument(
        "--bus-path",
        type=Path,
        default=_REPO_ROOT / "src" / "hassette" / "bus" / "bus.py",
        help="Path to bus.py (default: hassette/bus/bus.py)",
    )
    parser.add_argument(
        "--scheduler-path",
        type=Path,
        default=_REPO_ROOT / "src" / "hassette" / "scheduler" / "scheduler.py",
        help="Path to scheduler.py (default: hassette/scheduler/scheduler.py)",
    )
    parser.add_argument(
        "--target",
        choices=["api", "recording", "bus", "scheduler", "helpers", "all"],
        default="all",
        help="Which facade to generate. 'all' = every facade (default: all)",
    )
    parser.add_argument(
        "--helpers-path",
        type=Path,
        default=None,
        help="Path to helpers.py (default: alongside api.py as helpers.py)",
    )
    parser.add_argument(
        "--helpers-out",
        type=Path,
        default=None,
        help="Output path for sync_helpers.py (default: alongside api.py as sync_helpers.py)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check mode: exit 1 if generated content differs from committed file",
    )

    args = parser.parse_args(argv)

    api_path: Path = args.api_path
    if not api_path.exists():
        raise SystemExit(f"api.py not found at {api_path}")

    recording_api_path: Path = args.recording_api_path
    recording_out: Path = args.recording_out
    out_path: Path = args.out or api_path.with_name("sync.py")
    bus_path: Path = args.bus_path
    scheduler_path: Path = args.scheduler_path
    helpers_path: Path = args.helpers_path or api_path.with_name("helpers.py")
    helpers_out: Path = args.helpers_out or api_path.with_name("sync_helpers.py")

    run_api = args.target in ("api", "all")
    run_recording = args.target in ("recording", "all")
    run_bus = args.target in ("bus", "all")
    run_scheduler = args.target in ("scheduler", "all")
    run_helpers = args.target in ("helpers", "all")

    any_drift = False

    if run_api:
        api_code = generate_sync(api_path)
        if args.check:
            if not _check_drift(out_path, api_code, "ApiSyncFacade"):
                any_drift = True
        else:
            _atomic_write_generated(out_path, api_code)
            print(f"Wrote {out_path}")

    if run_recording:
        if not recording_api_path.exists():
            raise SystemExit(f"recording_api.py not found at {recording_api_path}")
        recording_code = generate_sync_recording(api_path, recording_api_path)
        if args.check:
            if not _check_drift(recording_out, recording_code, "RecordingSyncFacade"):
                any_drift = True
        else:
            _atomic_write_generated(recording_out, recording_code)
            print(f"Wrote {recording_out}")

    if run_bus:
        if not bus_path.exists():
            raise SystemExit(f"bus.py not found at {bus_path}")
        bus_out = bus_path.with_name("sync.py")
        bus_code = generate_sync_bus(bus_path)
        if args.check:
            if not _check_drift(bus_out, bus_code, "BusSyncFacade"):
                any_drift = True
        else:
            _atomic_write_generated(bus_out, bus_code)
            print(f"Wrote {bus_out}")

    if run_scheduler:
        if not scheduler_path.exists():
            raise SystemExit(f"scheduler.py not found at {scheduler_path}")
        scheduler_out = scheduler_path.with_name("sync.py")
        scheduler_code = generate_sync_scheduler(scheduler_path)
        if args.check:
            if not _check_drift(scheduler_out, scheduler_code, "SchedulerSyncFacade"):
                any_drift = True
        else:
            _atomic_write_generated(scheduler_out, scheduler_code)
            print(f"Wrote {scheduler_out}")

    if run_helpers:
        if not helpers_path.exists():
            raise SystemExit(f"helpers.py not found at {helpers_path}")
        helpers_code = generate_sync_helpers(helpers_path)
        if args.check:
            if not _check_drift(helpers_out, helpers_code, "HelperClientSyncFacade"):
                any_drift = True
        else:
            _atomic_write_generated(helpers_out, helpers_code)
            print(f"Wrote {helpers_out}")

    if args.check and any_drift:
        sys.exit(1)
