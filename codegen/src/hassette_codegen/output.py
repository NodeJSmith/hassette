"""Shared output utilities: ruff formatting, per-file validation, atomic write, drift checking."""

import contextlib
import difflib
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path


def _run_ruff_quiet(cmd: list[str], step_name: str) -> None:
    """Run a ruff subprocess step with stdout suppressed."""
    try:
        subprocess.run(cmd, check=True, timeout=30, stdout=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise SystemExit("ruff not found on PATH. Install with: uv tool install ruff") from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"ruff {step_name} timed out after 30s — check for filesystem stall") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"ruff {step_name} failed with exit code {exc.returncode}.") from exc


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

        _run_ruff_quiet(["ruff", "format", tmp_path], "format")
        _run_ruff_quiet(["ruff", "check", "--fix", "--ignore", "S105", tmp_path], "fix")

        return Path(tmp_path).read_text(encoding="utf-8")
    finally:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                Path(tmp_path).unlink()


def run_ruff(path: Path, *, logical_path: Path | None = None) -> None:
    """Run ruff format + fix all auto-fixable violations, then validate.

    Pass logical_path when the file lives in a temp location but should be
    validated as if it were at logical_path — this ensures per-file-ignores
    in ruff.toml match on the final filename, not the temp name.

    The check step uses ruff's stdin mode (pipe content in, receive fixed
    content out) so --stdin-filename applies correctly. The format step
    operates on the file directly — ruff format output is independent of the
    filename, so per-file-ignores routing via --stdin-filename isn't needed there.
    """
    _run_ruff_quiet(["ruff", "format", str(path)], "format")
    if logical_path is not None:
        # Pipe through stdin so --stdin-filename controls per-file-ignores lookup.
        # S105 stays ignored for generated code (test-token-like string literals).
        content = path.read_bytes()
        try:
            result = subprocess.run(
                ["ruff", "check", "--fix", "--ignore", "S105", "--stdin-filename", str(logical_path), "-"],
                input=content,
                capture_output=True,
                timeout=30,
            )
        except FileNotFoundError as exc:
            raise SystemExit("ruff not found on PATH. Install with: uv tool install ruff") from exc
        except subprocess.TimeoutExpired as exc:
            raise SystemExit("ruff fix timed out after 30s — check for filesystem stall") from exc
        if result.returncode not in (0, 1):
            sys.stderr.buffer.write(result.stderr)
            raise SystemExit(f"ruff fix failed with exit code {result.returncode}.")
        # Stdin mode emits the (possibly partially) fixed source on stdout even when
        # unfixable violations remain (returncode 1). Persist it before deciding the
        # verdict so no applied fix is ever discarded by a future caller; the current
        # caller (atomic_write) discards the temp file on SystemExit regardless.
        path.write_bytes(result.stdout)
        if result.returncode == 1:
            sys.stderr.buffer.write(result.stderr)
            raise SystemExit("ruff fix failed with exit code 1 (unfixable violations).")
    else:
        _run_ruff_quiet(["ruff", "check", "--fix", "--ignore", "S105", str(path)], "fix")


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
            run_ruff(tmp_path, logical_path=out_path)
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
    diff = difflib.unified_diff(
        normalized_committed.splitlines(keepends=True),
        normalized_generated.splitlines(keepends=True),
        fromfile=f"committed/{target_path.name}",
        tofile=f"generated/{target_path.name}",
        n=3,
    )
    sys.stderr.writelines(diff)
    return False
