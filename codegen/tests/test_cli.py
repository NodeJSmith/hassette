"""Unit tests for the CLI argument parsing and dispatch."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.__main__ import _build_parser, main


class TestArgParsing:
    def test_no_args_returns_zero(self) -> None:
        with patch("sys.argv", ["hassette-codegen"]):
            assert main() == 0

    def test_help_flag(self, capsys) -> None:
        parser = _build_parser()
        args = parser.parse_args(["generate", "--ha-core-path", "/tmp/fake", "--check"])
        assert args.command == "generate"
        assert args.check is True
        assert args.ha_core_path == Path("/tmp/fake")

    def test_domain_filter_parsed(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["generate", "--ha-core-path", "/tmp", "--domain", "light,fan"])
        assert args.domain == "light,fan"

    def test_sync_facade_subcommand(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["sync-facade", "--check"])
        assert args.command == "sync-facade"
        assert args.check is True
