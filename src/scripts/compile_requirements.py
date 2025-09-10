#!/usr/bin/env -S uv run --script

from collections.abc import Iterable
from pathlib import Path

CONFIG_PATH = Path("/config")
APPS_PATH = Path("/apps")


ALLOWED_FILE_NAMES = ("requirements.txt", "hassette-requirements.txt")
OUTPUT_PATH = Path("/tmp/merged_requirements.txt")


def find_req_files(root: Path, names: tuple[str, ...]) -> list[Path]:
    hits: list[Path] = []
    for name in names:
        hits.extend(root.rglob(name))
    return [p for p in hits if p.is_file() and p.stat().st_size > 0]


def read_lines_dedup(paths: Iterable[Path]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for raw in txt.splitlines():
            line = raw.strip().replace("\r", "")
            if not line or line.startswith("#"):
                continue
            if line not in seen:
                seen.add(line)
                out.append(line)
    return out


def main() -> int:
    if not CONFIG_PATH.exists():
        print("Config path /config does not exist, cannot continue")
        return 1

    if not APPS_PATH.exists():
        print("Apps path /apps does not exist, cannot continue")
        return 1

    config_files = find_req_files(CONFIG_PATH, ALLOWED_FILE_NAMES)
    app_files = find_req_files(APPS_PATH, ALLOWED_FILE_NAMES)
    files = config_files + app_files

    lines = read_lines_dedup(files)

    if not lines:
        print(f"No requirements files found in {CONFIG_PATH}, exiting")
        return 0

    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Merged {len(files)} file(s) into {OUTPUT_PATH} with {len(lines)} unique requirements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
