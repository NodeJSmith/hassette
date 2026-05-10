"""CLI entry point for hassette-codegen."""

import argparse
import sys
from pathlib import Path

_CODEGEN_SRC = str(Path(__file__).resolve().parent.parent)
if _CODEGEN_SRC not in sys.path:
    sys.path.insert(0, _CODEGEN_SRC)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hassette-codegen",
        description="Generate typed entity wrappers, state models, and constants from Home Assistant core",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Entity generation (default command)
    gen_parser = subparsers.add_parser("generate", help="Generate entity code from HA core")
    gen_parser.add_argument("--ha-core-path", type=Path, help="Path to local HA core checkout")
    gen_parser.add_argument("--ha-release-tag", type=str, help="HA release tag to clone (e.g., 2026.5.1)")
    gen_parser.add_argument("--check", action="store_true", help="Check for drift without writing files")
    gen_parser.add_argument("--domain", type=str, help="Comma-separated list of domains to generate")

    # Sync facade subcommand
    sf_parser = subparsers.add_parser("sync-facade", help="Generate the sync facade for hassette")
    sf_parser.add_argument("--check", action="store_true", help="Check for drift without writing")

    return parser


def _run_sync_facade(args: argparse.Namespace) -> int:
    from hassette_codegen.sync_facade import main as sf_main

    sys.argv = ["generate_sync_facade"]
    if args.check:
        sys.argv.append("--check")
    try:
        sf_main()
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "sync-facade":
        return _run_sync_facade(args)

    if args.command == "generate":
        from hassette_codegen.ha_source import resolve_source
        from hassette_codegen.pipeline import run_pipeline

        ha_source = resolve_source(ha_core_path=args.ha_core_path, ha_release_tag=args.ha_release_tag)
        try:
            repo_root = Path(__file__).resolve().parent.parent.parent.parent
            domain_filter = set(args.domain.split(",")) if args.domain else None
            return run_pipeline(ha_source, repo_root, check_mode=args.check, domain_filter=domain_filter)
        finally:
            ha_source.cleanup()

    return 0


if __name__ == "__main__":
    sys.exit(main())
