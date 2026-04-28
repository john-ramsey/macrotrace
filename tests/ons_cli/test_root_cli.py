from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from macrotrace.cli import build_parser, main


def test_build_parser_returns_argument_parser():
    """build_parser returns an ArgumentParser instance."""
    parser = build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


def test_build_parser_ons_explorer_captures_remaining_args():
    """The root CLI recognises the nested ONS explorer command."""
    args = build_parser().parse_args(["ons", "explorer"])
    assert args.command == "ons"
    assert args.ons_command == "explorer"


def test_build_parser_ons_tui_captures_remaining_args():
    """The root CLI recognises the nested ONS TUI command."""
    args = build_parser().parse_args(["ons", "tui"])
    assert args.command == "ons"
    assert args.ons_command == "tui"


def test_main_dispatches_to_ons_explorer():
    """main dispatches `macrotrace ons explorer ...` to the explorer CLI."""
    with patch("macrotrace.ons_cli.cli.main", return_value=0) as mock_main:
        result = main(["ons", "explorer", "datasets"])

    assert result == 0
    mock_main.assert_called_once_with(["datasets"])


def test_main_dispatches_to_ons_tui():
    """main dispatches `macrotrace ons tui ...` to the TUI CLI."""
    with patch("macrotrace.ons_cli.tui.main", return_value=0) as mock_main:
        result = main(["ons", "tui", "--help"])

    assert result == 0
    mock_main.assert_called_once_with(["--help"])


def test_main_prints_nested_help_for_ons(capsys):
    """main shows nested help for `macrotrace ons --help`."""
    with pytest.raises(SystemExit):
        main(["ons", "--help"])

    out = capsys.readouterr().out
    assert "explorer" in out
    assert "tui" in out


def test_main_requires_top_level_command():
    """main exits if no top-level command is provided."""
    with pytest.raises(SystemExit):
        main([])


def test_main_prints_top_level_help():
    """`macrotrace --help` exits cleanly through argparse."""
    with pytest.raises(SystemExit):
        main(["--help"])


def test_main_rejects_unknown_top_level_command():
    """An unknown top-level command falls through to argparse and exits."""
    with pytest.raises(SystemExit):
        main(["definitely-not-a-command"])


def test_main_rejects_unknown_ons_subcommand():
    """An unknown `ons` subcommand falls through to argparse and exits."""
    with pytest.raises(SystemExit):
        main(["ons", "definitely-not-a-subcommand"])
