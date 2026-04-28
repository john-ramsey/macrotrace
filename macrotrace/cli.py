"""Top-level Macrotrace command-line interface."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional


def _run_ons_explorer(args: argparse.Namespace) -> int:
    from macrotrace.ons_cli.cli import main as ons_main

    return ons_main(args.args)


def _run_ons_tui(args: argparse.Namespace) -> int:
    from macrotrace.ons_cli.tui import main as ons_tui_main

    return ons_tui_main(args.args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="macrotrace",
        description="Macrotrace command-line tools.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ons_parser = subparsers.add_parser(
        "ons",
        help="ONS explorer commands.",
        description="ONS explorer commands.",
    )
    ons_subparsers = ons_parser.add_subparsers(dest="ons_command", required=True)

    ons_subparsers.add_parser(
        "explorer",
        help="Run the interactive ONS explorer CLI.",
        description="Run the interactive ONS explorer CLI.",
    )
    ons_subparsers.add_parser(
        "tui",
        help="Run the Textual ONS explorer TUI.",
        description="Run the Textual ONS explorer TUI.",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    if not argv:
        parser.parse_args(argv)

    if argv == ["--help"] or argv == ["-h"]:
        parser.parse_args(argv)

    if argv[0] != "ons":
        parser.parse_args(argv)

    if len(argv) == 1 or argv[1] in {"-h", "--help"}:
        parser.parse_args(argv)

    if argv[1] == "explorer":
        return _run_ons_explorer(argparse.Namespace(args=argv[2:]))

    if argv[1] == "tui":
        return _run_ons_tui(argparse.Namespace(args=argv[2:]))

    parser.parse_args(argv)
    return 2
