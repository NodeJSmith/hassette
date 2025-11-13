"""Generate per-module reference stubs for mkdocstrings."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import mkdocs_gen_files

ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT / "src"
VIRTUAL_REF_ROOT = Path("reference")
DEBUG = bool(os.environ.get("GEN_REF_DEBUG"))


def format_title(part: str) -> str:
    return " ".join(word.capitalize() for word in part.split("_"))


def main() -> None:
    nav = mkdocs_gen_files.Nav()

    ref_disk_dir = ROOT / "docs" / VIRTUAL_REF_ROOT
    if ref_disk_dir.exists():
        shutil.rmtree(ref_disk_dir)

    if DEBUG:
        print("[gen-ref] generating API reference stubs...", flush=True)

    for path in sorted(SRC_DIR.rglob("*.py")):
        module_parts = path.relative_to(SRC_DIR).with_suffix("").parts

        if not module_parts:
            continue

        if module_parts[-1] in {"__main__", "__version__"}:
            continue

        doc_path = Path(*module_parts).with_suffix(".md")
        full_doc_path = VIRTUAL_REF_ROOT / doc_path
        parts = module_parts

        if parts[-1] == "__init__":
            parts = parts[:-1]
            if not parts:
                continue
            doc_path = doc_path.with_name("index.md")
            full_doc_path = full_doc_path.with_name("index.md")

        nav_entry = [format_title(part) for part in parts]
        nav[nav_entry] = doc_path.as_posix()

        if DEBUG:
            print(f"[gen-ref] writing {full_doc_path} for {'.'.join(parts)}")

        with mkdocs_gen_files.open(full_doc_path, "w") as fd:
            fd.write(f"::: {'.'.join(parts)}\n")

        mkdocs_gen_files.set_edit_path(full_doc_path, path.relative_to(ROOT))

    summary_path = VIRTUAL_REF_ROOT / "SUMMARY.md"
    with mkdocs_gen_files.open(summary_path, "w") as nav_file:
        nav_file.writelines(nav.build_literate_nav())


if __name__ in {"__main__", "<run_path>"}:
    main()
