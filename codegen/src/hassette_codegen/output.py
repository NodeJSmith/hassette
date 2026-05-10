"""Shared output utilities: ruff formatting, per-file validation, atomic write, drift checking."""

import contextlib
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path


def run_ruff_step(cmd: list[str], step_name: str) -> None:
    """Run a single ruff subprocess step, raising SystemExit on failure."""
    try:
        subprocess.run(cmd, check=True, timeout=30)
    except FileNotFoundError as exc:
        raise SystemExit("ruff not found on PATH. Install with: uv tool install ruff") from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"ruff {step_name} timed out after 30s — check for filesystem stall") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"ruff {step_name} failed with exit code {exc.returncode}. See the ruff output above for details."
        ) from exc


def format_via_ruff(content: str) -> str:
    """Normalize Python source through ruff format + isort, return the result.

    Writes to a temp file outside the repo so --check mode never leaves artifacts.
    Applies only byte-affecting steps (format + isort fix), not validation.
    """
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            dir=tempfile.gettempdir(),
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        run_ruff_step(["ruff", "format", tmp_path], "format")
        run_ruff_step(["ruff", "check", "--fix", "--select", "I", tmp_path], "isort")

        return Path(tmp_path).read_text(encoding="utf-8")
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                Path(tmp_path).unlink()


def run_ruff(path: Path) -> None:
    """Run ruff format + import-sort fix + ruff check on a file path."""
    run_ruff_step(["ruff", "format", str(path)], "format")
    run_ruff_step(["ruff", "check", "--fix", "--select", "I", str(path)], "isort")
    run_ruff_step(["ruff", "check", str(path)], "check")


def atomic_write(out_path: Path, content: str) -> bool:
    """Atomically write generated source after ruff + py_compile validation.

    Returns True if the file was written successfully, False if validation failed
    (the file is skipped and its previous version is retained).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf8",
            dir=out_path.parent,
            prefix=f".{out_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as fp:
            fp.write(content)
            tmp_path = Path(fp.name)

        try:
            run_ruff(tmp_path)
        except SystemExit:
            print(f"WARNING: {out_path} failed ruff validation — skipping (previous version retained)", file=sys.stderr)
            return False

        try:
            py_compile.compile(str(tmp_path), doraise=True)
        except py_compile.PyCompileError:
            print(f"WARNING: {out_path} failed py_compile — skipping (previous version retained)", file=sys.stderr)
            return False

        tmp_path.replace(out_path)
        tmp_path = None
        return True
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink()


def check_drift(target_path: Path, generated_content: str, label: str = "") -> bool:
    """Check if target_path content matches generated_content after ruff normalization.

    Returns True if in-sync, False if drift detected.
    """
    if not target_path.exists():
        display = label or target_path.name
        print(f"{display} is out of date (target file does not exist).", file=sys.stderr)
        return False

    committed_content = target_path.read_text(encoding="utf-8")
    normalized_committed = format_via_ruff(committed_content)
    normalized_generated = format_via_ruff(generated_content)

    if normalized_committed == normalized_generated:
        return True

    display = label or target_path.name
    print(f"{display} is out of date.", file=sys.stderr)
    return False
