import argparse
import json
from unittest.mock import MagicMock, patch

import pytest

from macrotrace.ons_cli.cli import (
    _apply_contains_filter,
    _browse_dimensions_and_options,
    _interactive_pick_code,
    _interactive_select_item,
    _parse_kv_pairs,
    _print_json,
    _print_series_key_result,
    _print_table,
    _series_key_query_string,
    _slice_for_display,
    build_parser,
    cmd_browse,
    cmd_datasets,
    cmd_dimensions,
    cmd_editions,
    cmd_inspect,
    cmd_options,
    cmd_series_key,
    cmd_versions,
    main,
)

from tests.ons_cli.utils import (  # noqa: F401  pytest fixtures
    SAMPLE_CODE_LIST_EDITIONS,
    SAMPLE_CODES,
    SAMPLE_DATASETS,
    SAMPLE_DIMENSIONS,
    SAMPLE_EDITIONS,
    SAMPLE_VERSIONS,
    explorer,
    explorer_client,
    mock_session,
)


def test_parse_kv_pairs_valid():
    """Parses a list of 'key=value' strings into a dictionary."""
    result = _parse_kv_pairs(["aggregate=cpih1dim1A0", "geography=K02000001"])
    assert result == {"aggregate": "cpih1dim1A0", "geography": "K02000001"}


def test_parse_kv_pairs_empty_list():
    """Returns an empty dict when given an empty list."""
    assert _parse_kv_pairs([]) == {}


def test_parse_kv_pairs_value_contains_equals():
    """Splits only on the first '=' so values can contain '=' characters."""
    result = _parse_kv_pairs(["key=val=ue"])
    assert result == {"key": "val=ue"}


def test_parse_kv_pairs_missing_equals_raises():
    """Raises ValueError when a token has no '=' separator."""
    with pytest.raises(ValueError, match="Invalid --set value"):
        _parse_kv_pairs(["no-equals-sign"])


def test_parse_kv_pairs_empty_key_raises():
    """Raises ValueError when the key portion is empty."""
    with pytest.raises(ValueError, match="non-empty"):
        _parse_kv_pairs(["=value"])


def test_parse_kv_pairs_empty_value_raises():
    """Raises ValueError when the value portion is empty."""
    with pytest.raises(ValueError, match="non-empty"):
        _parse_kv_pairs(["key="])


def test_parse_kv_pairs_strips_whitespace():
    """Strips surrounding whitespace from both key and value."""
    result = _parse_kv_pairs([" key = value "])
    assert result == {"key": "value"}


def test_print_json_outputs_indented_json(capsys):
    """Prints a dict as valid indented JSON to stdout."""
    _print_json({"id": "cpih01", "title": "CPIH"})
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed == {"id": "cpih01", "title": "CPIH"}


def test_print_json_handles_list(capsys):
    """Prints a list as valid JSON to stdout."""
    _print_json([1, 2, 3])
    out = capsys.readouterr().out
    assert json.loads(out) == [1, 2, 3]


def test_print_table_empty_rows(capsys):
    """Prints 'No results.' when the row list is empty."""
    _print_table([], ["col1", "col2"])
    out = capsys.readouterr().out
    assert "No results." in out


def test_print_table_prints_headers(capsys):
    """Prints column headers above the data rows."""
    _print_table([["a", "b"]], ["col1", "col2"])
    out = capsys.readouterr().out
    assert "col1" in out
    assert "col2" in out


def test_series_key_query_string_single():
    """Formats a single-entry series key as a query string."""
    qs = _series_key_query_string({"aggregate": "cpih1dim1A0"})
    assert qs == "aggregate=cpih1dim1A0"


def test_series_key_query_string_multiple():
    """Formats a multi-entry series key with all pairs present."""
    qs = _series_key_query_string({"a": "1", "b": "2"})
    assert "a=1" in qs
    assert "b=2" in qs


def test_series_key_query_string_empty():
    """Returns an empty string for an empty series key."""
    assert _series_key_query_string({}) == ""


def test_apply_contains_filter_no_filter():
    """Returns all rows unchanged when contains is None."""
    rows = [{"id": "cpih01", "title": "CPIH"}, {"id": "gdp", "title": "GDP"}]
    result = _apply_contains_filter(rows, contains=None, fields=["id", "title"])
    assert result == rows


def test_apply_contains_filter_matches():
    """Keeps only rows whose fields contain the filter substring."""
    rows = [{"id": "cpih01", "title": "CPIH"}, {"id": "gdp", "title": "GDP"}]
    result = _apply_contains_filter(rows, contains="cpih", fields=["id", "title"])
    assert len(result) == 1
    assert result[0]["id"] == "cpih01"


def test_apply_contains_filter_case_insensitive():
    """Matches the filter substring case-insensitively."""
    rows = [{"id": "cpih01", "title": "Consumer Price Inflation"}]
    result = _apply_contains_filter(rows, contains="CONSUMER", fields=["title"])
    assert len(result) == 1


def test_apply_contains_filter_no_matches():
    """Returns an empty list when no rows match the filter."""
    rows = [{"id": "cpih01"}, {"id": "gdp"}]
    result = _apply_contains_filter(rows, contains="xyz", fields=["id"])
    assert result == []


def test_slice_for_display_respects_limit():
    """Truncates the row list to the given limit when show_all is False."""
    rows = [{"id": str(i)} for i in range(10)]
    result = _slice_for_display(rows, show_all=False, limit=3)
    assert len(result) == 3


def test_slice_for_display_show_all():
    """Returns all rows when show_all is True, ignoring limit."""
    rows = [{"id": str(i)} for i in range(10)]
    result = _slice_for_display(rows, show_all=True, limit=3)
    assert len(result) == 10


def test_slice_for_display_zero_limit():
    """Returns an empty list when limit is zero."""
    rows = [{"id": "x"}]
    result = _slice_for_display(rows, show_all=False, limit=0)
    assert result == []


def test_build_parser_returns_argument_parser():
    """build_parser returns an ArgumentParser instance."""
    parser = build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


def test_build_parser_datasets_command():
    """The 'datasets' subcommand is recognized with correct defaults."""
    parser = build_parser()
    args = parser.parse_args(["datasets"])
    assert args.command == "datasets"
    assert args.json is False
    assert args.show_all is False


def test_build_parser_editions_command():
    """The 'editions' subcommand accepts a dataset_id positional argument."""
    parser = build_parser()
    args = parser.parse_args(["editions", "cpih01"])
    assert args.command == "editions"
    assert args.dataset_id == "cpih01"


def test_build_parser_versions_command():
    """The 'versions' subcommand accepts --edition."""
    parser = build_parser()
    args = parser.parse_args(["versions", "cpih01", "--edition", "time-series"])
    assert args.command == "versions"
    assert args.edition == "time-series"


def test_build_parser_dimensions_command():
    """The 'dimensions' subcommand accepts --version."""
    parser = build_parser()
    args = parser.parse_args(["dimensions", "cpih01", "--version", "latest"])
    assert args.command == "dimensions"
    assert args.version == "latest"


def test_build_parser_options_command():
    """The 'options' subcommand accepts a dimension positional argument."""
    parser = build_parser()
    args = parser.parse_args(["options", "cpih01", "aggregate"])
    assert args.command == "options"
    assert args.dimension == "aggregate"


def test_build_parser_series_key_command():
    """The 'series-key' subcommand accepts --set, --non-interactive, and --json."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "series-key",
            "cpih01",
            "--set",
            "aggregate=cpih1dim1A0",
            "--non-interactive",
            "--json",
        ]
    )
    assert args.command == "series-key"
    assert args.set == ["aggregate=cpih1dim1A0"]
    assert args.non_interactive is True
    assert args.json is True


def test_build_parser_no_cache_flag():
    """The global --no-cache flag is recognized and defaults to False."""
    parser = build_parser()
    args = parser.parse_args(["--no-cache", "datasets"])
    assert args.no_cache is True


def test_build_parser_requires_subcommand():
    """Parsing with no subcommand raises SystemExit."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def _make_args(**kwargs):
    """Build a simple namespace with sensible defaults for cmd tests."""
    defaults = {
        "page_size": 100,
        "max_pages": 5,
        "contains": None,
        "skip_time_series_check": True,
        "time_series_only": False,
        "show_all": True,
        "limit": 100,
        "json": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_cmd_datasets_table_output(explorer, capsys):
    """cmd_datasets prints dataset IDs in tabular format."""
    explorer.list_datasets = MagicMock(return_value=SAMPLE_DATASETS)
    args = _make_args()
    cmd_datasets(explorer, args)
    out = capsys.readouterr().out
    assert "cpih01" in out


def test_cmd_datasets_json_output(explorer, capsys):
    """cmd_datasets prints valid JSON when --json is set."""
    explorer.list_datasets = MagicMock(return_value=SAMPLE_DATASETS)
    args = _make_args(json=True)
    cmd_datasets(explorer, args)
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert parsed[0]["id"] == "cpih01"


def test_cmd_datasets_raises_if_time_series_only_and_skip_check(explorer):
    """cmd_datasets raises ValueError when --time-series-only and --skip-time-series-check are both set."""
    explorer.list_datasets = MagicMock(return_value=SAMPLE_DATASETS)
    args = _make_args(skip_time_series_check=True, time_series_only=True)
    with pytest.raises(ValueError, match="Cannot use"):
        cmd_datasets(explorer, args)


def test_cmd_datasets_with_contains_filter(explorer, capsys):
    """cmd_datasets applies the --contains filter to dataset output."""
    explorer.list_datasets = MagicMock(return_value=SAMPLE_DATASETS)
    args = _make_args(contains="cpih")
    cmd_datasets(explorer, args)
    out = capsys.readouterr().out
    assert "cpih01" in out
    assert "gdp" not in out


def test_cmd_editions_table_output(explorer, capsys):
    """cmd_editions prints edition names in tabular format."""
    explorer.list_editions = MagicMock(return_value=SAMPLE_EDITIONS)
    args = argparse.Namespace(dataset_id="cpih01", json=False)
    cmd_editions(explorer, args)
    out = capsys.readouterr().out
    assert "time-series" in out


def test_cmd_editions_json_output(explorer, capsys):
    """cmd_editions prints valid JSON when --json is set."""
    explorer.list_editions = MagicMock(return_value=SAMPLE_EDITIONS)
    args = argparse.Namespace(dataset_id="cpih01", json=True)
    cmd_editions(explorer, args)
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed[0]["edition"] == "time-series"


def test_cmd_versions_table_output(explorer, capsys):
    """cmd_versions prints version release dates in tabular format."""
    explorer.list_versions = MagicMock(return_value=SAMPLE_VERSIONS)
    args = argparse.Namespace(dataset_id="cpih01", edition="time-series", json=False)
    cmd_versions(explorer, args)
    out = capsys.readouterr().out
    assert "2024-01-01" in out


def test_cmd_versions_json_output(explorer, capsys):
    """cmd_versions prints valid JSON when --json is set."""
    explorer.list_versions = MagicMock(return_value=SAMPLE_VERSIONS)
    args = argparse.Namespace(dataset_id="cpih01", edition="time-series", json=True)
    cmd_versions(explorer, args)
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert isinstance(parsed, list)


def test_cmd_dimensions_table_output(explorer, capsys):
    """cmd_dimensions prints dimension names in tabular format."""
    explorer.resolve_version = MagicMock(return_value={"version": 3})
    explorer.list_dimensions = MagicMock(return_value=SAMPLE_DIMENSIONS)
    args = argparse.Namespace(
        dataset_id="cpih01", edition="time-series", version="latest", json=False
    )
    cmd_dimensions(explorer, args)
    out = capsys.readouterr().out
    assert "aggregate" in out


def test_cmd_dimensions_json_output(explorer, capsys):
    """cmd_dimensions prints valid JSON with a 'dimensions' key when --json is set."""
    explorer.resolve_version = MagicMock(return_value={"version": 3})
    explorer.list_dimensions = MagicMock(return_value=SAMPLE_DIMENSIONS)
    args = argparse.Namespace(
        dataset_id="cpih01", edition="time-series", version="latest", json=True
    )
    cmd_dimensions(explorer, args)
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "dimensions" in parsed


def test_cmd_options_table_output(explorer, capsys):
    """cmd_options prints option codes in tabular format."""
    explorer.resolve_version = MagicMock(return_value={"version": 3})
    explorer.list_dimensions = MagicMock(return_value=SAMPLE_DIMENSIONS)
    explorer.resolve_dimension = MagicMock(return_value=SAMPLE_DIMENSIONS[0])
    explorer.list_dimension_options = MagicMock(
        return_value=("time-series", SAMPLE_CODES)
    )
    args = argparse.Namespace(
        dataset_id="cpih01",
        edition="time-series",
        version="latest",
        dimension="aggregate",
        code_list_edition=None,
        contains=None,
        show_all=True,
        limit=100,
        json=False,
    )
    cmd_options(explorer, args)
    out = capsys.readouterr().out
    assert "cpih1dim1A0" in out


def test_cmd_options_json_output(explorer, capsys):
    """cmd_options prints valid JSON with an 'options' key when --json is set."""
    explorer.resolve_version = MagicMock(return_value={"version": 3})
    explorer.list_dimensions = MagicMock(return_value=SAMPLE_DIMENSIONS)
    explorer.resolve_dimension = MagicMock(return_value=SAMPLE_DIMENSIONS[0])
    explorer.list_dimension_options = MagicMock(
        return_value=("time-series", SAMPLE_CODES)
    )
    args = argparse.Namespace(
        dataset_id="cpih01",
        edition="time-series",
        version="latest",
        dimension="aggregate",
        code_list_edition=None,
        contains=None,
        show_all=True,
        limit=100,
        json=True,
    )
    cmd_options(explorer, args)
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "options" in parsed


def test_cmd_options_raises_when_no_code_list(explorer, capsys):
    """cmd_options raises ValueError when the resolved dimension has no code list."""
    explorer.resolve_version = MagicMock(return_value={"version": 3})
    explorer.list_dimensions = MagicMock(return_value=SAMPLE_DIMENSIONS)
    no_code_list_dim = {
        "name": "aggregate",
        "id": "agg",
        "label": "Aggregate",
        "links": {},
    }
    explorer.resolve_dimension = MagicMock(return_value=no_code_list_dim)
    args = argparse.Namespace(
        dataset_id="cpih01",
        edition="time-series",
        version="latest",
        dimension="aggregate",
        code_list_edition=None,
        contains=None,
        show_all=True,
        limit=100,
        json=False,
    )
    with pytest.raises(ValueError, match="no code list"):
        cmd_options(explorer, args)


def _make_series_key_args(**kwargs):
    defaults = {
        "dataset_id": "cpih01",
        "edition": "time-series",
        "version": "latest",
        "set": ["aggregate=cpih1dim1A0"],
        "non_interactive": True,
        "preview_limit": 20,
        "json": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_cmd_series_key_non_interactive_json_output(explorer, capsys):
    """cmd_series_key writes a valid JSON series key in non-interactive mode."""
    version_item = {
        "version": 3,
        "release_date": "2024-01-01T00:00:00Z",
        "dimensions": [{"name": "time", "id": "mmm-yy"}],
    }
    explorer.resolve_version = MagicMock(return_value=version_item)
    explorer.list_dimensions = MagicMock(
        return_value=[
            {
                "name": "aggregate",
                "id": "cpih1dim1A0",
                "label": "Aggregate",
                "links": {
                    "code_list": {
                        "id": "cpih1dim1A0",
                        "edition": "time-series",
                    }
                },
            }
        ]
    )
    explorer.list_dimension_options = MagicMock(
        return_value=("time-series", [{"code": "cpih1dim1A0", "label": "All items"}])
    )
    args = _make_series_key_args(json=True)
    cmd_series_key(explorer, args)
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["series_key"] == {"aggregate": "cpih1dim1A0"}


def test_cmd_series_key_raises_for_invalid_edition(explorer):
    """cmd_series_key raises ValueError when the edition is not 'time-series'."""
    args = _make_series_key_args(edition="2021")
    with pytest.raises(ValueError, match="time-series"):
        cmd_series_key(explorer, args)


def test_cmd_series_key_raises_when_no_time_dimension(explorer):
    """cmd_series_key raises ValueError when the dataset version has no time dimension."""
    version_item = {
        "version": 3,
        "release_date": "2024-01-01T00:00:00Z",
        "dimensions": [],
    }
    explorer.resolve_version = MagicMock(return_value=version_item)
    explorer.get_version_metadata = MagicMock(return_value={"dimensions": []})
    explorer.list_dimensions = MagicMock(return_value=[])
    args = _make_series_key_args()
    with pytest.raises(ValueError, match="no time dimension"):
        cmd_series_key(explorer, args)


def test_cmd_series_key_raises_when_invalid_code_provided(explorer):
    """cmd_series_key raises ValueError when a --set code is not in the valid options."""
    version_item = {
        "version": 3,
        "dimensions": [{"name": "time", "id": "mmm-yy"}],
    }
    explorer.resolve_version = MagicMock(return_value=version_item)
    explorer.list_dimensions = MagicMock(
        return_value=[
            {
                "name": "aggregate",
                "id": "cpih1dim1A0",
                "label": "Aggregate",
                "links": {"code_list": {"id": "cpih1dim1A0", "edition": "time-series"}},
            }
        ]
    )
    explorer.list_dimension_options = MagicMock(
        return_value=("time-series", [{"code": "VALID_CODE", "label": "Valid"}])
    )
    args = _make_series_key_args(set=["aggregate=INVALID_CODE"])
    with pytest.raises(ValueError, match="Invalid code"):
        cmd_series_key(explorer, args)


def test_cmd_series_key_non_interactive_raises_when_missing_set(explorer):
    """cmd_series_key raises ValueError when non-interactive mode has no --set values."""
    version_item = {
        "version": 3,
        "dimensions": [{"name": "time", "id": "mmm-yy"}],
    }
    explorer.resolve_version = MagicMock(return_value=version_item)
    explorer.list_dimensions = MagicMock(
        return_value=[
            {
                "name": "aggregate",
                "id": "cpih1dim1A0",
                "label": "Aggregate",
                "links": {"code_list": {"id": "cpih1dim1A0", "edition": "time-series"}},
            }
        ]
    )
    explorer.list_dimension_options = MagicMock(
        return_value=("time-series", [{"code": "cpih1dim1A0", "label": "All items"}])
    )
    args = _make_series_key_args(set=[], non_interactive=True)
    with pytest.raises(ValueError, match="Missing --set"):
        cmd_series_key(explorer, args)


def test_cmd_inspect_json_output(explorer, capsys):
    """cmd_inspect prints a valid JSON summary of dataset, editions, versions, and dimensions."""
    explorer.get_dataset = MagicMock(
        return_value={"id": "cpih01", "title": "CPIH", "description": "", "links": {}}
    )
    explorer.list_editions = MagicMock(return_value=SAMPLE_EDITIONS)
    explorer.list_versions = MagicMock(return_value=SAMPLE_VERSIONS)
    explorer.resolve_version = MagicMock(return_value={"version": 3})
    explorer.list_dimensions = MagicMock(return_value=SAMPLE_DIMENSIONS)
    args = argparse.Namespace(
        dataset_id="cpih01",
        edition="time-series",
        version="latest",
        json=True,
    )
    cmd_inspect(explorer, args)
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["dataset"]["id"] == "cpih01"
    assert "editions" in parsed


def test_cmd_inspect_table_output(explorer, capsys):
    """cmd_inspect prints dataset ID and title in tabular format."""
    explorer.get_dataset = MagicMock(
        return_value={
            "id": "cpih01",
            "title": "CPIH",
            "description": "Desc",
            "links": {},
        }
    )
    explorer.list_editions = MagicMock(return_value=SAMPLE_EDITIONS)
    explorer.list_versions = MagicMock(return_value=SAMPLE_VERSIONS)
    explorer.resolve_version = MagicMock(return_value={"version": 3})
    explorer.list_dimensions = MagicMock(return_value=SAMPLE_DIMENSIONS)
    args = argparse.Namespace(
        dataset_id="cpih01",
        edition="time-series",
        version="latest",
        json=False,
    )
    cmd_inspect(explorer, args)
    out = capsys.readouterr().out
    assert "cpih01" in out
    assert "CPIH" in out


def test_cmd_inspect_edition_not_found_message(explorer, capsys):
    """cmd_inspect prints a 'not found' message when the requested edition is absent."""
    explorer.get_dataset = MagicMock(
        return_value={"id": "cpih01", "title": "CPIH", "description": "", "links": {}}
    )
    explorer.list_editions = MagicMock(return_value=SAMPLE_EDITIONS)
    args = argparse.Namespace(
        dataset_id="cpih01",
        edition="nonexistent-edition",
        version="latest",
        json=False,
    )
    cmd_inspect(explorer, args)
    out = capsys.readouterr().out
    assert "not found" in out


def test_main_returns_0_on_success():
    """main returns exit code 0 when a command completes without error."""
    with (
        patch("macrotrace.ons_cli.cli.ONSExplorerClient") as MockClient,
        patch("macrotrace.ons_cli.cli.ONSExplorer") as MockExplorer,
    ):
        mock_explorer = MagicMock()
        mock_explorer.list_datasets.return_value = []
        MockExplorer.return_value = mock_explorer

        rc = main(["--no-cache", "datasets", "--skip-time-series-check"])
        assert rc == 0


def test_main_returns_1_on_error():
    """main returns exit code 1 when a command raises a RuntimeError."""
    with (
        patch("macrotrace.ons_cli.cli.ONSExplorerClient") as MockClient,
        patch("macrotrace.ons_cli.cli.ONSExplorer") as MockExplorer,
    ):
        mock_explorer = MagicMock()
        mock_explorer.list_datasets.side_effect = RuntimeError("boom")
        MockExplorer.return_value = mock_explorer

        rc = main(["--no-cache", "datasets", "--skip-time-series-check"])
        assert rc == 1


def test_main_returns_130_on_keyboard_interrupt():
    """main returns exit code 130 when a command raises KeyboardInterrupt."""
    with (
        patch("macrotrace.ons_cli.cli.ONSExplorerClient") as MockClient,
        patch("macrotrace.ons_cli.cli.ONSExplorer") as MockExplorer,
    ):
        mock_explorer = MagicMock()
        mock_explorer.list_datasets.side_effect = KeyboardInterrupt("quit")
        MockExplorer.return_value = mock_explorer

        rc = main(["--no-cache", "datasets", "--skip-time-series-check"])
        assert rc == 130


def test_main_clears_cache_when_flag_set():
    """main calls clear_cache on the client when --clear-cache is passed."""
    with (
        patch("macrotrace.ons_cli.cli.ONSExplorerClient") as MockClient,
        patch("macrotrace.ons_cli.cli.ONSExplorer") as MockExplorer,
    ):
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        mock_explorer = MagicMock()
        mock_explorer.list_datasets.return_value = []
        MockExplorer.return_value = mock_explorer

        main(["--no-cache", "--clear-cache", "datasets", "--skip-time-series-check"])
        mock_client.clear_cache.assert_called_once()


def _make_select_kwargs(items, page_size=10, allow_back=True):
    return dict(
        title="Test",
        items=items,
        headers=["id"],
        row_builder=lambda item: [item["id"]],
        search_text_builder=lambda item: item["id"],
        page_size=page_size,
        allow_back=allow_back,
    )


def test_interactive_select_item_empty_items_returns_none(capsys):
    """Returns None and prints 'No results.' when the item list is empty."""
    result = _interactive_select_item(**_make_select_kwargs([]))
    assert result is None
    assert "No results." in capsys.readouterr().out


def test_interactive_select_item_selects_first_item():
    """Returns the first item when the user enters '1'."""
    items = [{"id": "a"}, {"id": "b"}]
    with patch("builtins.input", return_value="1"):
        result = _interactive_select_item(**_make_select_kwargs(items))
    assert result == {"id": "a"}


def test_interactive_select_item_selects_second_item():
    """Returns the second item when the user enters '2'."""
    items = [{"id": "a"}, {"id": "b"}]
    with patch("builtins.input", return_value="2"):
        result = _interactive_select_item(**_make_select_kwargs(items))
    assert result == {"id": "b"}


def test_interactive_select_item_quit_raises_keyboard_interrupt():
    """Raises KeyboardInterrupt when the user enters 'q'."""
    with patch("builtins.input", return_value="q"):
        with pytest.raises(KeyboardInterrupt):
            _interactive_select_item(**_make_select_kwargs([{"id": "a"}]))


def test_interactive_select_item_exit_raises_keyboard_interrupt():
    """Raises KeyboardInterrupt when the user enters 'exit'."""
    with patch("builtins.input", return_value="exit"):
        with pytest.raises(KeyboardInterrupt):
            _interactive_select_item(**_make_select_kwargs([{"id": "a"}]))


def test_interactive_select_item_eoferror_raises_keyboard_interrupt():
    """Raises KeyboardInterrupt when input raises EOFError."""
    with patch("builtins.input", side_effect=EOFError()):
        with pytest.raises(KeyboardInterrupt):
            _interactive_select_item(**_make_select_kwargs([{"id": "a"}]))


def test_interactive_select_item_back_returns_none():
    """Returns None when the user enters 'b' (go back) and back is allowed."""
    with patch("builtins.input", return_value="b"):
        result = _interactive_select_item(**_make_select_kwargs([{"id": "a"}]))
    assert result is None


def test_interactive_select_item_back_disabled_not_a_command(capsys):
    """Prints 'Invalid command' when back is disabled and the user enters 'b'."""
    items = [{"id": "a"}]
    with patch("builtins.input", side_effect=["b", "q"]):
        with pytest.raises(KeyboardInterrupt):
            _interactive_select_item(**_make_select_kwargs(items, allow_back=False))
    assert "Invalid command" in capsys.readouterr().out


def test_interactive_select_item_next_page():
    """Advances to the next page and returns the correct item."""
    items = [{"id": str(i)} for i in range(6)]
    with patch("builtins.input", side_effect=["n", "2"]):
        result = _interactive_select_item(**_make_select_kwargs(items, page_size=3))
    assert result == {"id": "4"}  # page 2, item 2


def test_interactive_select_item_next_on_last_page_prints_message(capsys):
    """Prints 'last page' when the user tries to advance past the final page."""
    items = [{"id": "a"}, {"id": "b"}]
    with patch("builtins.input", side_effect=["n", "1"]):
        result = _interactive_select_item(**_make_select_kwargs(items, page_size=10))
    assert "last page" in capsys.readouterr().out
    assert result == {"id": "a"}


def test_interactive_select_item_prev_page():
    """Goes back to the previous page and returns the correct item."""
    items = [{"id": str(i)} for i in range(6)]
    with patch("builtins.input", side_effect=["n", "p", "1"]):
        result = _interactive_select_item(**_make_select_kwargs(items, page_size=3))
    assert result == {"id": "0"}


def test_interactive_select_item_prev_on_first_page_prints_message(capsys):
    """Prints 'first page' when the user tries to go back from the first page."""
    items = [{"id": "a"}]
    with patch("builtins.input", side_effect=["p", "1"]):
        result = _interactive_select_item(**_make_select_kwargs(items))
    assert "first page" in capsys.readouterr().out
    assert result == {"id": "a"}


def test_interactive_select_item_filter_then_select():
    """Filters items with '/query' and returns the matching item when selected."""
    items = [{"id": "cpih01"}, {"id": "gdp"}]
    with patch("builtins.input", side_effect=["/cpih", "1"]):
        result = _interactive_select_item(**_make_select_kwargs(items))
    assert result == {"id": "cpih01"}


def test_interactive_select_item_clear_filter_shows_all():
    """Clears the active filter with '/' and shows all items again."""
    items = [{"id": "cpih01"}, {"id": "gdp"}]
    with patch("builtins.input", side_effect=["/cpih", "/", "2"]):
        result = _interactive_select_item(**_make_select_kwargs(items))
    assert result == {"id": "gdp"}


def test_interactive_select_item_filter_no_results(capsys):
    """Prints 'No items on this page' when the filter matches nothing."""
    items = [{"id": "cpih01"}]
    with patch("builtins.input", side_effect=["/xyz", "q"]):
        with pytest.raises(KeyboardInterrupt):
            _interactive_select_item(**_make_select_kwargs(items))
    assert "No items on this page" in capsys.readouterr().out


def test_interactive_select_item_invalid_number_prints_message(capsys):
    """Prints 'Invalid selection' when the user enters an out-of-range number."""
    items = [{"id": "a"}]
    with patch("builtins.input", side_effect=["99", "1"]):
        result = _interactive_select_item(**_make_select_kwargs(items))
    assert "Invalid selection" in capsys.readouterr().out
    assert result == {"id": "a"}


def test_interactive_select_item_invalid_command_prints_message(capsys):
    """Prints 'Invalid command' when the user enters an unrecognised string."""
    items = [{"id": "a"}]
    with patch("builtins.input", side_effect=["xyz", "1"]):
        result = _interactive_select_item(**_make_select_kwargs(items))
    assert "Invalid command" in capsys.readouterr().out
    assert result == {"id": "a"}


def _make_pick_code_kwargs(options=None):
    if options is None:
        options = [
            {"code": "cpih1dim1A0", "label": "All items"},
            {"code": "cpih1dim1G10100", "label": "Food"},
        ]
    return dict(
        dimension_id="aggregate",
        dimension_label="Aggregate",
        options=options,
        preview_limit=10,
    )


def test_interactive_pick_code_no_options_raises():
    """Raises ValueError when no options are available for the dimension."""
    with pytest.raises(ValueError, match="No options available"):
        _interactive_pick_code(**_make_pick_code_kwargs(options=[]))


def test_interactive_pick_code_valid_code_selected():
    """Returns the entered code when it is a valid option."""
    with patch("builtins.input", return_value="cpih1dim1A0"):
        result = _interactive_pick_code(**_make_pick_code_kwargs())
    assert result == "cpih1dim1A0"


def test_interactive_pick_code_quit_raises_keyboard_interrupt():
    """Raises KeyboardInterrupt when the user enters 'q'."""
    with patch("builtins.input", return_value="q"):
        with pytest.raises(KeyboardInterrupt):
            _interactive_pick_code(**_make_pick_code_kwargs())


def test_interactive_pick_code_list_command_then_select(capsys):
    """Prints option codes after 'list' and then returns the chosen code."""
    with patch("builtins.input", side_effect=["list", "cpih1dim1A0"]):
        result = _interactive_pick_code(**_make_pick_code_kwargs())
    assert result == "cpih1dim1A0"
    assert "cpih1dim1A0" in capsys.readouterr().out


def test_interactive_pick_code_filter_then_select():
    """Filters options with '/query' and returns the code entered afterwards."""
    with patch("builtins.input", side_effect=["/food", "cpih1dim1G10100"]):
        result = _interactive_pick_code(**_make_pick_code_kwargs())
    assert result == "cpih1dim1G10100"


def test_interactive_pick_code_empty_input_ignored():
    """Ignores blank input and waits for a non-empty response."""
    with patch("builtins.input", side_effect=["", "cpih1dim1A0"]):
        result = _interactive_pick_code(**_make_pick_code_kwargs())
    assert result == "cpih1dim1A0"


def test_interactive_pick_code_invalid_code_then_valid(capsys):
    """Prints 'not a valid code' for an invalid code and then accepts a valid one."""
    with patch("builtins.input", side_effect=["BOGUS", "cpih1dim1A0"]):
        result = _interactive_pick_code(**_make_pick_code_kwargs())
    assert result == "cpih1dim1A0"
    assert "not a valid code" in capsys.readouterr().out


def test_interactive_pick_code_filter_too_many_results(capsys):
    """Prints 'Showing first N' when filtered results exceed preview_limit."""
    options = [{"code": f"code{i}", "label": f"Label {i}"} for i in range(20)]
    with patch("builtins.input", side_effect=["/code", "code0"]):
        result = _interactive_pick_code(
            dimension_id="agg",
            dimension_label="Aggregate",
            options=options,
            preview_limit=5,
        )
    assert result == "code0"
    assert "Showing first 5" in capsys.readouterr().out


def test_cmd_datasets_annotates_has_time_series(explorer, capsys):
    """cmd_datasets annotates datasets with has_time_series=True when the edition is found."""
    explorer.list_datasets = MagicMock(return_value=SAMPLE_DATASETS[:1])
    explorer.list_editions = MagicMock(return_value=[{"edition": "time-series"}])
    args = _make_args(skip_time_series_check=False, time_series_only=False)
    cmd_datasets(explorer, args)
    out = capsys.readouterr().out
    assert "True" in out


def test_cmd_datasets_time_series_only_filters(explorer, capsys):
    """cmd_datasets excludes datasets without a time-series edition when --time-series-only is set."""
    datasets = [
        {"id": "cpih01", "title": "CPIH", "description": ""},
        {"id": "gdp", "title": "GDP", "description": ""},
    ]
    explorer.list_datasets = MagicMock(return_value=datasets)
    explorer.list_editions = MagicMock(
        side_effect=lambda ds_id: (
            [{"edition": "time-series"}] if ds_id == "cpih01" else []
        )
    )
    args = _make_args(skip_time_series_check=False, time_series_only=True)
    cmd_datasets(explorer, args)
    out = capsys.readouterr().out
    assert "cpih01" in out
    assert "gdp" not in out


def test_cmd_series_key_raises_for_unsupported_frequency(explorer):
    """cmd_series_key raises ValueError when the time dimension has an unsupported frequency."""
    version_item = {
        "version": 3,
        "dimensions": [{"name": "time", "id": "unknown-unsupported-freq"}],
    }
    explorer.resolve_version = MagicMock(return_value=version_item)
    explorer.list_dimensions = MagicMock(return_value=[])
    args = _make_series_key_args()
    with pytest.raises(ValueError, match="unsupported time"):
        cmd_series_key(explorer, args)


def test_cmd_series_key_no_non_time_dims_prints_message(explorer, capsys):
    """cmd_series_key prints 'No non-time dimensions' when all dimensions are time dimensions."""
    version_item = {
        "version": 3,
        "dimensions": [{"name": "time", "id": "mmm-yy"}],
    }
    explorer.resolve_version = MagicMock(return_value=version_item)
    explorer.list_dimensions = MagicMock(
        return_value=[{"name": "time", "id": "mmm-yy", "label": "Time", "links": {}}]
    )
    args = _make_series_key_args(set=[], non_interactive=True)
    cmd_series_key(explorer, args)
    out = capsys.readouterr().out
    assert "No non-time dimensions" in out


def test_cmd_series_key_falls_back_to_get_version_metadata(explorer, capsys):
    """cmd_series_key falls back to get_version_metadata when dimensions are absent from resolve_version."""
    version_item = {"version": 3}
    explorer.resolve_version = MagicMock(return_value=version_item)
    explorer.get_version_metadata = MagicMock(
        return_value={"dimensions": [{"name": "time", "id": "mmm-yy"}]}
    )
    explorer.list_dimensions = MagicMock(
        return_value=[
            {
                "name": "aggregate",
                "id": "cpih1dim1A0",
                "label": "Aggregate",
                "links": {"code_list": {"id": "cpih1dim1A0", "edition": "time-series"}},
            }
        ]
    )
    explorer.list_dimension_options = MagicMock(
        return_value=("time-series", [{"code": "cpih1dim1A0", "label": "All items"}])
    )
    args = _make_series_key_args(json=True)
    cmd_series_key(explorer, args)
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["series_key"] == {"aggregate": "cpih1dim1A0"}


def test_cmd_series_key_raises_when_dim_has_no_code_list(explorer):
    """cmd_series_key raises ValueError when a dimension specified via --set has no code list."""
    version_item = {"version": 3, "dimensions": [{"name": "time", "id": "mmm-yy"}]}
    explorer.resolve_version = MagicMock(return_value=version_item)
    explorer.list_dimensions = MagicMock(
        return_value=[
            {"name": "aggregate", "id": "agg", "label": "Aggregate", "links": {}}
        ]
    )
    args = _make_series_key_args(set=["aggregate=val"])
    with pytest.raises(ValueError, match="no code list"):
        cmd_series_key(explorer, args)


def test_cmd_series_key_text_output(explorer, capsys):
    """cmd_series_key prints a human-readable summary including the query string and MTTimeSeries snippet."""
    version_item = {"version": 3, "dimensions": [{"name": "time", "id": "mmm-yy"}]}
    explorer.resolve_version = MagicMock(return_value=version_item)
    explorer.list_dimensions = MagicMock(
        return_value=[
            {
                "name": "aggregate",
                "id": "cpih1dim1A0",
                "label": "Aggregate",
                "links": {"code_list": {"id": "cpih1dim1A0", "edition": "time-series"}},
            }
        ]
    )
    explorer.list_dimension_options = MagicMock(
        return_value=("time-series", [{"code": "cpih1dim1A0", "label": "All items"}])
    )
    args = _make_series_key_args(json=False)
    cmd_series_key(explorer, args)
    out = capsys.readouterr().out
    assert "Series key generated" in out
    assert "Query string" in out
    assert "MTTimeSeries" in out


def test_cmd_series_key_interactive_pick(explorer, capsys):
    """cmd_series_key prompts the user interactively and produces a JSON payload when non_interactive=False."""
    version_item = {"version": 3, "dimensions": [{"name": "time", "id": "mmm-yy"}]}
    explorer.resolve_version = MagicMock(return_value=version_item)
    explorer.list_dimensions = MagicMock(
        return_value=[
            {
                "name": "aggregate",
                "id": "cpih1dim1A0",
                "label": "Aggregate",
                "links": {"code_list": {"id": "cpih1dim1A0", "edition": "time-series"}},
            }
        ]
    )
    explorer.list_dimension_options = MagicMock(
        return_value=("time-series", [{"code": "cpih1dim1A0", "label": "All items"}])
    )
    args = _make_series_key_args(set=[], non_interactive=False, json=True)
    with patch("builtins.input", return_value="cpih1dim1A0"):
        cmd_series_key(explorer, args)
    out = capsys.readouterr().out
    assert '"aggregate": "cpih1dim1A0"' in out
    assert "query_string" in out


def test_print_series_key_result(capsys):
    """_print_series_key_result prints the series key, query string, and MTTimeSeries snippet."""
    _print_series_key_result("cpih01", "time-series", "3", {"aggregate": "cpih1dim1A0"})
    out = capsys.readouterr().out
    assert "Series key generated" in out
    assert "Query string" in out
    assert "MTTimeSeries" in out
    assert "cpih01" in out


def _make_browse_dim_explorer(explorer, *, time_dim_id="mmm-yy", dims=None):
    version_item = {"version": 3, "dimensions": [{"name": "time", "id": time_dim_id}]}
    explorer.resolve_version = MagicMock(return_value=version_item)
    explorer.list_dimensions = MagicMock(
        return_value=dims if dims is not None else SAMPLE_DIMENSIONS
    )
    explorer.list_dimension_options = MagicMock(
        return_value=("time-series", SAMPLE_CODES)
    )
    return explorer


def test_browse_dimensions_non_time_series_edition_exits_early(explorer, capsys):
    """_browse_dimensions_and_options prints a time-series requirement message for non-time-series editions."""
    _browse_dimensions_and_options(
        explorer, dataset_id="cpih01", edition="2021", version="3", preview_limit=20
    )
    out = capsys.readouterr().out
    assert "time-series" in out


def test_browse_dimensions_no_time_dim_exits_early(explorer, capsys):
    """_browse_dimensions_and_options exits early and prints a message when no time dimension is found."""
    explorer.resolve_version = MagicMock(return_value={"version": 3, "dimensions": []})
    explorer.get_version_metadata = MagicMock(return_value={"dimensions": []})
    _browse_dimensions_and_options(
        explorer,
        dataset_id="cpih01",
        edition="time-series",
        version="3",
        preview_limit=20,
    )
    out = capsys.readouterr().out
    assert "no time dimension" in out


def test_browse_dimensions_unsupported_frequency_exits_early(explorer, capsys):
    """_browse_dimensions_and_options exits early and prints 'unsupported' for unknown frequencies."""
    version_item = {
        "version": 3,
        "dimensions": [{"name": "time", "id": "unsupported-xyz"}],
    }
    explorer.resolve_version = MagicMock(return_value=version_item)
    _browse_dimensions_and_options(
        explorer,
        dataset_id="cpih01",
        edition="time-series",
        version="3",
        preview_limit=20,
    )
    out = capsys.readouterr().out
    assert "unsupported" in out.lower()


def test_browse_dimensions_no_dimensions_exits_early(explorer, capsys):
    """_browse_dimensions_and_options prints 'No dimensions found' when the dimension list is empty."""
    _make_browse_dim_explorer(explorer, dims=[])
    _browse_dimensions_and_options(
        explorer,
        dataset_id="cpih01",
        edition="time-series",
        version="3",
        preview_limit=20,
    )
    out = capsys.readouterr().out
    assert "No dimensions found" in out


def test_browse_dimensions_back_exits(explorer):
    """_browse_dimensions_and_options returns normally when the user enters 'b' to go back."""
    _make_browse_dim_explorer(explorer)
    with patch("builtins.input", return_value="b"):
        _browse_dimensions_and_options(
            explorer,
            dataset_id="cpih01",
            edition="time-series",
            version="3",
            preview_limit=20,
        )


def test_browse_dimensions_quit_raises(explorer):
    """_browse_dimensions_and_options raises KeyboardInterrupt when the user quits."""
    _make_browse_dim_explorer(explorer)
    with patch("builtins.input", return_value="q"):
        with pytest.raises(KeyboardInterrupt):
            _browse_dimensions_and_options(
                explorer,
                dataset_id="cpih01",
                edition="time-series",
                version="3",
                preview_limit=20,
            )


def test_browse_dimensions_done_with_empty_key(explorer, capsys):
    """_browse_dimensions_and_options prints a warning when done is entered with no selections."""
    _make_browse_dim_explorer(explorer)
    with patch("builtins.input", return_value="d"):
        _browse_dimensions_and_options(
            explorer,
            dataset_id="cpih01",
            edition="time-series",
            version="3",
            preview_limit=20,
        )
    out = capsys.readouterr().out
    assert "No non-time dimension selections" in out


def test_browse_dimensions_clear_then_back(explorer):
    """_browse_dimensions_and_options clears the series key on 'c' and then exits on 'b'."""
    _make_browse_dim_explorer(explorer)
    with patch("builtins.input", side_effect=["c", "b"]):
        _browse_dimensions_and_options(
            explorer,
            dataset_id="cpih01",
            edition="time-series",
            version="3",
            preview_limit=20,
        )


def test_browse_dimensions_invalid_command_then_back(explorer, capsys):
    """_browse_dimensions_and_options prints 'Invalid command' for unrecognised input."""
    _make_browse_dim_explorer(explorer)
    with patch("builtins.input", side_effect=["xyz", "b"]):
        _browse_dimensions_and_options(
            explorer,
            dataset_id="cpih01",
            edition="time-series",
            version="3",
            preview_limit=20,
        )
    assert "Invalid command" in capsys.readouterr().out


def test_browse_dimensions_invalid_number_then_back(explorer, capsys):
    """_browse_dimensions_and_options prints 'Invalid dimension number' for out-of-range indices."""
    _make_browse_dim_explorer(explorer)
    with patch("builtins.input", side_effect=["99", "b"]):
        _browse_dimensions_and_options(
            explorer,
            dataset_id="cpih01",
            edition="time-series",
            version="3",
            preview_limit=20,
        )
    assert "Invalid dimension number" in capsys.readouterr().out


def test_browse_dimensions_dim_no_code_list_then_back(explorer, capsys):
    """_browse_dimensions_and_options prints 'does not expose a code list' for dimensions without one."""
    _make_browse_dim_explorer(
        explorer, dims=[{"name": "agg", "id": "agg", "label": "Agg", "links": {}}]
    )
    with patch("builtins.input", side_effect=["1", "b"]):
        _browse_dimensions_and_options(
            explorer,
            dataset_id="cpih01",
            edition="time-series",
            version="3",
            preview_limit=20,
        )
    assert "does not expose a code list" in capsys.readouterr().out


def _make_browse_args(**kwargs):
    defaults = dict(
        page_size=100,
        max_pages=5,
        contains=None,
        skip_time_series_check=True,
        time_series_only=False,
        preview_limit=20,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_cmd_browse_raises_when_flags_conflict(explorer):
    """cmd_browse raises ValueError when --time-series-only and --skip-time-series-check are both set."""
    explorer.list_datasets = MagicMock(return_value=SAMPLE_DATASETS)
    with pytest.raises(ValueError, match="Cannot use"):
        cmd_browse(
            explorer,
            _make_browse_args(skip_time_series_check=True, time_series_only=True),
        )


def test_cmd_browse_empty_after_filter(explorer, capsys):
    """cmd_browse prints 'No datasets available' when the contains filter matches nothing."""
    explorer.list_datasets = MagicMock(return_value=SAMPLE_DATASETS)
    args = _make_browse_args(contains="zzz_no_match")
    cmd_browse(explorer, args)
    assert "No datasets available" in capsys.readouterr().out


def test_cmd_browse_quits_on_select_none(explorer):
    """cmd_browse exits gracefully when _interactive_select_item returns None."""
    explorer.list_datasets = MagicMock(return_value=SAMPLE_DATASETS)
    with patch("macrotrace.ons_cli.cli._interactive_select_item", return_value=None):
        cmd_browse(explorer, _make_browse_args())


def test_cmd_browse_skips_dataset_with_no_id(explorer, capsys):
    """cmd_browse prints 'no id' and continues when a selected dataset has an empty id."""
    explorer.list_datasets = MagicMock(return_value=SAMPLE_DATASETS)
    with patch(
        "macrotrace.ons_cli.cli._interactive_select_item",
        side_effect=[{"id": ""}, None],
    ):
        cmd_browse(explorer, _make_browse_args())
    assert "no id" in capsys.readouterr().out


def test_cmd_browse_annotates_time_series(explorer):
    """cmd_browse annotates datasets with time-series availability when skip_time_series_check is False."""
    explorer.list_datasets = MagicMock(return_value=SAMPLE_DATASETS[:1])
    explorer.list_editions = MagicMock(return_value=[{"edition": "time-series"}])
    with patch("macrotrace.ons_cli.cli._interactive_select_item", return_value=None):
        cmd_browse(explorer, _make_browse_args(skip_time_series_check=False))


def test_cmd_browse_ineligible_dataset_continues(explorer, capsys):
    """cmd_browse prints 'not eligible' and loops when a selected dataset raises on resolve_version."""
    explorer.list_datasets = MagicMock(return_value=SAMPLE_DATASETS)
    explorer.resolve_version = MagicMock(side_effect=ValueError("No versions"))
    with patch(
        "macrotrace.ons_cli.cli._interactive_select_item",
        side_effect=[SAMPLE_DATASETS[0], None],
    ):
        cmd_browse(explorer, _make_browse_args())
    assert "not eligible" in capsys.readouterr().out
