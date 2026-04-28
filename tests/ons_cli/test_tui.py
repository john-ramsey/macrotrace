from __future__ import annotations

import argparse
import time
from typing import Dict
from unittest.mock import MagicMock, patch

import pytest

from macrotrace.ons_cli.tui import ONSExplorerTUI, build_parser

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


@pytest.fixture
def tui(explorer):
    """ONSExplorerTUI instance with a mock explorer. No Textual event loop is started."""
    return ONSExplorerTUI(
        explorer,
        page_size=100,
        max_pages=5,
        preview_limit=20,
        time_series_only=True,
        skip_time_series_check=True,
        show_time_dimension=False,
        contains=None,
    )


def test_tui_build_parser_returns_argument_parser():
    """build_parser returns an ArgumentParser instance."""
    parser = build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


def test_tui_build_parser_defaults():
    """build_parser produces the expected default values for all flags."""
    args = build_parser().parse_args([])
    assert args.no_cache is False
    assert args.page_size == 1000
    assert args.max_pages == 50
    assert args.preview_limit == 25
    assert args.time_series_only is True
    assert args.skip_time_series_check is False
    assert args.show_time_dimension is False
    assert args.contains is None


def test_tui_build_parser_include_non_time_series():
    """--include-non-time-series sets time_series_only to False."""
    args = build_parser().parse_args(["--include-non-time-series"])
    assert args.time_series_only is False


def test_tui_build_parser_skip_time_series_check():
    """--skip-time-series-check sets skip_time_series_check to True."""
    args = build_parser().parse_args(["--skip-time-series-check"])
    assert args.skip_time_series_check is True


def test_tui_build_parser_contains():
    """--contains stores the provided substring."""
    args = build_parser().parse_args(["--contains", "cpih"])
    assert args.contains == "cpih"


def test_tui_build_parser_cache_flags():
    """--no-cache and --clear-cache are both recognized and stored."""
    args = build_parser().parse_args(["--no-cache", "--clear-cache"])
    assert args.no_cache is True
    assert args.clear_cache is True


def test_tui_init_sets_explorer(tui, explorer):
    """The explorer passed to __init__ is stored as tui.explorer."""
    assert tui.explorer is explorer


def test_tui_init_sets_params(tui):
    """Constructor parameters are stored as instance attributes."""
    assert tui.page_size == 100
    assert tui.max_pages == 5
    assert tui.preview_limit == 20
    assert tui.time_series_only is True
    assert tui.skip_time_series_check is True
    assert tui.show_time_dimension is False


def test_tui_init_default_navigation_state(tui):
    """Navigation state attributes are initialized to their default values."""
    assert tui.level == ONSExplorerTUI.LEVEL_DATASETS
    assert tui.selected_dataset_id is None
    assert tui.selected_edition is None
    assert tui.selected_version is None
    assert tui.selected_dimension is None
    assert tui.series_key == {}
    assert tui.startup_complete is False


def test_tui_init_contains_sets_initial_filter():
    """Passing contains='cpih' stores it in initial_contains."""
    app = ONSExplorerTUI(
        MagicMock(),
        page_size=100,
        max_pages=5,
        preview_limit=20,
        time_series_only=True,
        skip_time_series_check=True,
        show_time_dimension=False,
        contains="cpih",
    )
    assert app.initial_contains == "cpih"


def test_display_series_key_empty(tui):
    """Returns an empty dict when series_key is empty."""
    assert tui._display_series_key() == {}


def test_display_series_key_no_last_update(tui):
    """Returns series_key unchanged when last_series_update is None."""
    tui.series_key = {"agg": "cpih1dim1A0", "geo": "K02000001"}
    tui.last_series_update = None
    result = tui._display_series_key()
    assert result == {"agg": "cpih1dim1A0", "geo": "K02000001"}


def test_display_series_key_last_update_key_first(tui):
    """Puts the last-updated key first in the returned dict."""
    tui.series_key = {"agg": "cpih1dim1A0", "geo": "K02000001"}
    tui.last_series_update = ("geo", "K02000001")
    result = tui._display_series_key()
    keys = list(result.keys())
    assert keys[0] == "geo"


def test_display_series_key_last_update_key_not_in_series_key(tui):
    """Returns series_key as-is when last_series_update references a key not in series_key."""
    tui.series_key = {"agg": "cpih1dim1A0"}
    tui.last_series_update = ("removed_dim", "val")
    result = tui._display_series_key()
    assert result == {"agg": "cpih1dim1A0"}


def test_build_series_snippet_no_dataset(tui):
    """Returns None when no dataset has been selected."""
    assert tui._build_series_snippet() is None


def test_build_series_snippet_with_dataset(tui):
    """Returns a non-None string containing the dataset ID and 'MTTimeSeries'."""
    tui.selected_dataset_id = "cpih01"
    snippet = tui._build_series_snippet()
    assert snippet is not None
    assert "cpih01" in snippet
    assert "MTTimeSeries" in snippet


def test_build_series_snippet_includes_series_key(tui):
    """Includes the series key code in the snippet when one has been selected."""
    tui.selected_dataset_id = "cpih01"
    tui.series_key = {"agg": "cpih1dim1A0"}
    tui.last_series_update = ("agg", "cpih1dim1A0")
    snippet = tui._build_series_snippet()
    assert "cpih1dim1A0" in snippet


def test_order_editions_time_series_first(tui):
    """Sorts 'time-series' editions to the front of the list."""
    editions = [
        {"edition": "2021"},
        {"edition": "time-series"},
    ]
    result = tui._order_editions(editions)
    assert result[0]["edition"] == "time-series"
    assert result[0]["__edition_group"] == "time-series"


def test_order_editions_no_time_series_flags_others(tui):
    """Sets __no_time_series=True on all items when no time-series edition is present."""
    editions = [{"edition": "2021"}, {"edition": "2022"}]
    result = tui._order_editions(editions)
    for item in result:
        assert item.get("__no_time_series") is True


def test_order_editions_time_series_only_filters(tui):
    """Returns only time-series editions when time_series_only is True."""
    tui.time_series_only = True
    editions = [{"edition": "time-series"}, {"edition": "2021"}]
    result = tui._order_editions(editions)
    assert all(e["edition"] == "time-series" for e in result)


def test_order_editions_time_series_only_no_ts_returns_empty(tui):
    """Returns an empty list when time_series_only is True and no time-series edition exists."""
    tui.time_series_only = True
    editions = [{"edition": "2021"}, {"edition": "2022"}]
    result = tui._order_editions(editions)
    assert result == []


def test_order_editions_include_all_when_not_time_series_only(tui):
    """Returns all editions when time_series_only is False."""
    tui.time_series_only = False
    editions = [{"edition": "time-series"}, {"edition": "2021"}]
    result = tui._order_editions(editions)
    assert len(result) == 2


def test_resolve_series_key_support_success(tui, explorer):
    """Returns supported=True and a non-None frequency when the dataset has a recognized time dimension."""
    version_item = {"version": 3, "dimensions": [{"name": "time", "id": "mmm-yy"}]}
    explorer.resolve_version = MagicMock(return_value=version_item)
    supported, reason, time_dim_id, freq = tui._resolve_series_key_support_for_dataset(
        "cpih01"
    )
    assert supported is True
    assert reason is None
    assert time_dim_id == "mmm-yy"
    assert freq is not None


def test_resolve_series_key_support_resolve_version_raises(tui, explorer):
    """Returns supported=False with a reason when resolve_version raises ValueError."""
    explorer.resolve_version = MagicMock(side_effect=ValueError("No versions"))
    supported, reason, time_dim_id, freq = tui._resolve_series_key_support_for_dataset(
        "cpih01"
    )
    assert supported is False
    assert "Unable to validate" in reason
    assert time_dim_id is None


def test_resolve_series_key_support_no_time_dim(tui, explorer):
    """Returns supported=False with 'No time dimension' when the dataset has no time dimension."""
    version_item = {"version": 3, "dimensions": []}
    explorer.resolve_version = MagicMock(return_value=version_item)
    explorer.get_version_metadata = MagicMock(return_value={"dimensions": []})
    supported, reason, time_dim_id, freq = tui._resolve_series_key_support_for_dataset(
        "cpih01"
    )
    assert supported is False
    assert "No time dimension" in reason


def test_resolve_series_key_support_unsupported_freq(tui, explorer):
    """Returns supported=False with 'not supported' when the time dimension frequency is unknown."""
    version_item = {"version": 3, "dimensions": [{"name": "time", "id": "unknown-xyz"}]}
    explorer.resolve_version = MagicMock(return_value=version_item)
    supported, reason, time_dim_id, freq = tui._resolve_series_key_support_for_dataset(
        "cpih01"
    )
    assert supported is False
    assert "not supported" in reason
    assert time_dim_id == "unknown-xyz"
    assert freq is None


def test_resolve_series_key_support_metadata_fallback(tui, explorer):
    """Falls back to get_version_metadata to resolve the time dimension when dimensions are missing."""
    version_item = {"version": 3}  # No dimensions key
    explorer.resolve_version = MagicMock(return_value=version_item)
    explorer.get_version_metadata = MagicMock(
        return_value={"dimensions": [{"name": "time", "id": "mmm-yy"}]}
    )
    supported, reason, time_dim_id, freq = tui._resolve_series_key_support_for_dataset(
        "cpih01"
    )
    assert supported is True
    assert time_dim_id == "mmm-yy"


def test_resolve_series_key_support_metadata_raises(tui, explorer):
    """Returns supported=False when get_version_metadata raises an exception."""
    version_item = {"version": 3}
    explorer.resolve_version = MagicMock(return_value=version_item)
    explorer.get_version_metadata = MagicMock(side_effect=RuntimeError("network error"))
    supported, reason, time_dim_id, freq = tui._resolve_series_key_support_for_dataset(
        "cpih01"
    )
    assert supported is False
    assert "Unable to validate" in reason


def test_search_text_datasets_level(tui):
    """Returns a string containing id, title, and description at the DATASETS level."""
    tui.level = ONSExplorerTUI.LEVEL_DATASETS
    item = {"id": "cpih01", "title": "CPIH", "description": "inflation"}
    text = tui._search_text(item)
    assert "cpih01" in text
    assert "CPIH" in text
    assert "inflation" in text


def test_search_text_editions_level(tui):
    """Returns a string containing edition and block reason at the EDITIONS level."""
    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    item = {
        "edition": "time-series",
        "label": "Time Series",
        "__series_key_block_reason": "blocked",
    }
    text = tui._search_text(item)
    assert "time-series" in text
    assert "blocked" in text


def test_search_text_versions_level(tui):
    """Returns a string containing version number and release date at the VERSIONS level."""
    tui.level = ONSExplorerTUI.LEVEL_VERSIONS
    item = {"version": 3, "release_date": "2024-01-01"}
    text = tui._search_text(item)
    assert "3" in text
    assert "2024-01-01" in text


def test_search_text_dimensions_level(tui):
    """Returns a string containing dimension name at the DIMENSIONS level."""
    tui.level = ONSExplorerTUI.LEVEL_DIMENSIONS
    text = tui._search_text(SAMPLE_DIMENSIONS[0])
    assert "aggregate" in text.lower()


def test_search_text_options_level(tui):
    """Returns a string containing code and label at the OPTIONS level."""
    tui.level = ONSExplorerTUI.LEVEL_OPTIONS
    item = {"code": "cpih1dim1A0", "label": "All items"}
    text = tui._search_text(item)
    assert "cpih1dim1A0" in text
    assert "All items" in text


def test_search_text_unknown_level_returns_json(tui):
    """Falls back to JSON serialisation for unknown levels."""
    tui.level = "unknown"
    item = {"foo": "bar"}
    text = tui._search_text(item)
    assert "bar" in text


def test_format_item_datasets_with_time_series_only(tui):
    """Formats a dataset item including its ID and description at DATASETS level."""
    tui.level = ONSExplorerTUI.LEVEL_DATASETS
    tui.time_series_only = True
    item = {
        "id": "cpih01",
        "title": "CPIH",
        "description": "Desc",
        "has_time_series": True,
    }
    text = tui._format_item(item)
    assert "cpih01" in text
    assert "Desc" in text


def test_format_item_datasets_without_time_series_only(tui):
    """Includes 'Time-Series Edition' label when time_series_only is False and flag is set."""
    tui.level = ONSExplorerTUI.LEVEL_DATASETS
    tui.time_series_only = False
    item = {"id": "cpih01", "title": "CPIH", "description": "", "has_time_series": True}
    text = tui._format_item(item)
    assert "Time-Series Edition" in text


def test_format_item_editions_time_series_supported(tui):
    """Shows 'Enabled' and frequency when the time-series edition supports series keys."""
    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    item = {
        "edition": "time-series",
        "label": "Time Series",
        "__series_key_supported": True,
        "__resolved_frequency": "MS",
    }
    text = tui._format_item(item)
    assert "Enabled" in text
    assert "MS" in text


def test_format_item_editions_time_series_blocked(tui):
    """Shows 'Disabled' and the block reason when series key support is blocked."""
    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    item = {
        "edition": "time-series",
        "label": "Time Series",
        "__series_key_supported": False,
        "__series_key_block_reason": "Unsupported type",
    }
    text = tui._format_item(item)
    assert "Disabled" in text
    assert "Unsupported type" in text


def test_format_item_editions_other_edition(tui):
    """Shows 'Reference-Only' for non-time-series editions."""
    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    item = {"edition": "2021", "label": "2021 Edition"}
    text = tui._format_item(item)
    assert "Reference-Only" in text


def test_format_item_editions_no_time_series_note(tui):
    """Includes 'no time-series edition' note when __no_time_series is set."""
    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    item = {"edition": "2021", "label": "Label", "__no_time_series": True}
    text = tui._format_item(item)
    assert "no time-series edition" in text


def test_format_item_versions(tui):
    """Formats a version item showing version number and release date."""
    tui.level = ONSExplorerTUI.LEVEL_VERSIONS
    item = {"version": 3, "release_date": "2024-01-01"}
    text = tui._format_item(item)
    assert "Version: 3" in text
    assert "2024-01-01" in text


def test_format_item_dimensions_not_selected(tui):
    """Shows 'Not Selected' and '( )' when the dimension has no series key entry."""
    tui.level = ONSExplorerTUI.LEVEL_DIMENSIONS
    tui.series_key = {}
    text = tui._format_item(SAMPLE_DIMENSIONS[0])
    assert "Not Selected" in text
    assert "( )" in text


def test_format_item_dimensions_selected(tui):
    """Shows 'Selected' and '(x)' when the dimension has a series key entry."""
    tui.level = ONSExplorerTUI.LEVEL_DIMENSIONS
    tui.series_key = {"aggregate": "cpih1dim1A0"}
    text = tui._format_item(SAMPLE_DIMENSIONS[0])
    assert "Selected" in text
    assert "(x)" in text


def test_format_item_options(tui):
    """Formats an option item showing code and label."""
    tui.level = ONSExplorerTUI.LEVEL_OPTIONS
    item = {"code": "cpih1dim1A0", "label": "All items"}
    text = tui._format_item(item)
    assert "cpih1dim1A0" in text
    assert "All items" in text


def test_format_item_unknown_level(tui):
    """Returns a string (not None) for unknown levels."""
    tui.level = "unknown"
    text = tui._format_item({"any": "value"})
    assert isinstance(text, str)


def test_rate_limit_suffix_no_limit(tui):
    """Returns an empty string when rate_limit_until is zero."""
    tui.rate_limit_until = 0.0
    assert tui._rate_limit_suffix() == ""


def test_rate_limit_suffix_active(tui):
    """Returns a suffix containing the endpoint and 'retry in' when rate limiting is active."""
    tui.rate_limit_until = time.monotonic() + 10.0
    tui.rate_limit_endpoint = "datasets"
    suffix = tui._rate_limit_suffix()
    assert "datasets" in suffix
    assert "retry in" in suffix


def test_rate_limit_suffix_expired(tui):
    """Clears rate_limit_until and returns '' when the rate limit window has expired."""
    tui.rate_limit_until = time.monotonic() - 1.0
    tui.rate_limit_endpoint = "datasets"
    suffix = tui._rate_limit_suffix()
    assert suffix == ""
    assert tui.rate_limit_until == 0.0


def test_copy_to_clipboard_success(tui):
    """Returns True when the subprocess clipboard command succeeds."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = tui._copy_to_clipboard("some text")
    assert result is True


def test_copy_to_clipboard_subprocess_fails_tries_textual_api(tui):
    """Falls back to the Textual copy_to_clipboard API when subprocess fails."""
    with patch("subprocess.run", side_effect=Exception("no clipboard")):
        tui.copy_to_clipboard = MagicMock()
        result = tui._copy_to_clipboard("some text")
    assert result is True
    tui.copy_to_clipboard.assert_called_once_with("some text")


def test_copy_to_clipboard_all_fail_returns_false(tui):
    """Returns False when both subprocess and Textual clipboard APIs raise exceptions."""
    with patch("subprocess.run", side_effect=Exception("no clipboard")):
        with patch.object(tui, "copy_to_clipboard", side_effect=Exception("no api")):
            result = tui._copy_to_clipboard("some text")
    assert result is False


def test_log_loading_appends_message(tui):
    """Appends a new message to loading_logs."""
    tui._render_loading_or_status = MagicMock()
    tui._log_loading("Fetching datasets")
    assert "Fetching datasets" in tui.loading_logs


def test_log_loading_deduplicates_consecutive(tui):
    """Does not append a message that is identical to the previous one."""
    tui._render_loading_or_status = MagicMock()
    tui._log_loading("Same message")
    tui._log_loading("Same message")
    assert tui.loading_logs.count("Same message") == 1


def test_log_loading_trims_to_six_entries(tui):
    """Keeps loading_logs at most 6 entries."""
    tui._render_loading_or_status = MagicMock()
    for i in range(10):
        tui._log_loading(f"Message {i}")
    assert len(tui.loading_logs) <= 6


def test_log_loading_ignores_blank_message(tui):
    """Ignores whitespace-only messages and leaves loading_logs empty."""
    tui._render_loading_or_status = MagicMock()
    tui._log_loading("   ")
    assert tui.loading_logs == []


def test_on_rate_limited_updates_state(tui):
    """Sets rate_limit_until and rate_limit_endpoint when rate limiting is triggered."""
    tui._render_loading_or_status = MagicMock()
    tui._log_loading = MagicMock()
    before = time.monotonic()
    tui._on_rate_limited("datasets", 5.0)
    assert tui.rate_limit_until >= before + 5.0
    assert tui.rate_limit_endpoint == "datasets"


def test_on_rate_limited_uses_minimum_wait(tui):
    """Enforces a minimum wait time even when wait_seconds is zero."""
    tui._render_loading_or_status = MagicMock()
    tui._log_loading = MagicMock()
    before = time.monotonic()
    tui._on_rate_limited("datasets", 0.0)
    assert tui.rate_limit_until >= before + 0.1


def test_on_level_load_failed_ignores_stale_level(tui):
    """If the level has changed since the load was dispatched, ignore the failure."""
    tui._stop_loading = MagicMock()
    tui._render_option_list = MagicMock()
    tui._set_status = MagicMock()

    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    tui._on_level_load_failed(ONSExplorerTUI.LEVEL_DATASETS, "timeout")
    tui._stop_loading.assert_not_called()


def test_on_level_load_failed_clears_items(tui):
    """Clears current_items and filtered_items on a matching level failure."""
    tui._stop_loading = MagicMock()
    tui._finish_startup = MagicMock()
    tui._render_option_list = MagicMock()
    tui._set_status = MagicMock()

    tui.level = ONSExplorerTUI.LEVEL_DATASETS
    tui.current_items = [{"id": "x"}]
    tui._on_level_load_failed(ONSExplorerTUI.LEVEL_DATASETS, "timeout")
    assert tui.current_items == []
    assert tui.filtered_items == []


def test_on_level_loaded_ignores_stale_level(tui):
    """Does not update state when the loaded level no longer matches the current level."""
    tui._stop_loading = MagicMock()
    tui._apply_filter = MagicMock()
    tui._set_status = MagicMock()

    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    tui._on_level_loaded(ONSExplorerTUI.LEVEL_DATASETS, SAMPLE_DATASETS)
    tui._stop_loading.assert_not_called()


def test_on_level_loaded_updates_current_items(tui):
    """Sets current_items to the loaded items when the level matches."""
    tui._stop_loading = MagicMock()
    tui._finish_startup = MagicMock()
    tui._apply_filter = MagicMock()
    tui._set_status = MagicMock()

    tui.level = ONSExplorerTUI.LEVEL_DATASETS
    tui._on_level_loaded(ONSExplorerTUI.LEVEL_DATASETS, SAMPLE_DATASETS)
    assert tui.current_items == SAMPLE_DATASETS


def test_on_level_loaded_editions_auto_skip(tui):
    """Single selectable time-series edition should auto-advance to versions."""
    tui._stop_loading = MagicMock()
    tui._finish_startup = MagicMock()
    tui._apply_filter = MagicMock()
    tui._set_status = MagicMock()
    tui._clear_filter = MagicMock()
    tui._update_path = MagicMock()
    tui._refresh_current_level = MagicMock()

    supported_edition = {
        "edition": "time-series",
        "__series_key_supported": True,
    }
    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    tui._on_level_loaded(ONSExplorerTUI.LEVEL_EDITIONS, [supported_edition])
    assert tui.level == ONSExplorerTUI.LEVEL_VERSIONS
    assert tui.edition_step_skipped is True


def test_on_level_loaded_editions_no_time_series(tui):
    """Sets a 'No time-series edition' status message when no supported editions are loaded."""
    tui._stop_loading = MagicMock()
    tui._finish_startup = MagicMock()
    tui._apply_filter = MagicMock()
    tui._set_status = MagicMock()

    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    tui._on_level_loaded(ONSExplorerTUI.LEVEL_EDITIONS, [{"edition": "2021"}])
    call_args = tui._set_status.call_args[0][0]
    assert "No time-series edition" in call_args


def _mock_open_item_side_effects(tui):
    """Suppress all widget-touching calls so we can test state transitions."""
    tui._clear_filter = MagicMock()
    tui._update_path = MagicMock()
    tui._update_series_key_panel = MagicMock()
    tui._refresh_current_level = MagicMock()
    tui._set_status = MagicMock()


def test_open_item_ignores_out_of_range_index(tui):
    """Does nothing when the given index is beyond the filtered_items list."""
    _mock_open_item_side_effects(tui)
    tui.filtered_items = [{"id": "cpih01"}]
    tui._open_item_by_index(5)
    tui._refresh_current_level.assert_not_called()


def test_open_item_datasets_level_advances_to_editions(tui):
    """Advances level to EDITIONS and stores selected_dataset_id when a valid dataset is opened."""
    _mock_open_item_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_DATASETS
    tui.filtered_items = [{"id": "cpih01", "title": "CPIH"}]
    tui._open_item_by_index(0)
    assert tui.level == ONSExplorerTUI.LEVEL_EDITIONS
    assert tui.selected_dataset_id == "cpih01"


def test_open_item_datasets_level_no_id_sets_status(tui):
    """Calls _set_status and stays at DATASETS level when the dataset has an empty id."""
    _mock_open_item_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_DATASETS
    tui.filtered_items = [{"id": ""}]
    tui._open_item_by_index(0)
    assert tui.level == ONSExplorerTUI.LEVEL_DATASETS
    tui._set_status.assert_called()


def test_open_item_editions_level_advances_to_versions(tui):
    """Advances level to VERSIONS and stores selected_edition when a supported edition is opened."""
    _mock_open_item_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    tui.filtered_items = [{"edition": "time-series", "__series_key_supported": True}]
    tui._open_item_by_index(0)
    assert tui.level == ONSExplorerTUI.LEVEL_VERSIONS
    assert tui.selected_edition == "time-series"


def test_open_item_editions_non_time_series_sets_status(tui):
    """Calls _set_status and stays at EDITIONS level when a non-time-series edition is opened."""
    _mock_open_item_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    tui.filtered_items = [{"edition": "2021"}]
    tui._open_item_by_index(0)
    assert tui.level == ONSExplorerTUI.LEVEL_EDITIONS
    tui._set_status.assert_called()


def test_open_item_editions_blocked_sets_status(tui):
    """Calls _set_status and stays at EDITIONS level when series key support is blocked."""
    _mock_open_item_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    tui.filtered_items = [
        {
            "edition": "time-series",
            "__series_key_supported": False,
            "__series_key_block_reason": "bad",
        }
    ]
    tui._open_item_by_index(0)
    assert tui.level == ONSExplorerTUI.LEVEL_EDITIONS
    tui._set_status.assert_called()


def test_open_item_versions_level_advances_to_dimensions(tui):
    """Advances level to DIMENSIONS and stores selected_version when a version is opened."""
    _mock_open_item_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_VERSIONS
    tui.filtered_items = [{"version": 3}]
    tui._open_item_by_index(0)
    assert tui.level == ONSExplorerTUI.LEVEL_DIMENSIONS
    assert tui.selected_version == "3"


def test_open_item_versions_no_version_sets_status(tui):
    """Stays at VERSIONS level when the version item has an empty version field."""
    _mock_open_item_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_VERSIONS
    tui.filtered_items = [{"version": ""}]
    tui._open_item_by_index(0)
    assert tui.level == ONSExplorerTUI.LEVEL_VERSIONS


def test_open_item_dimensions_with_code_list_advances_to_options(tui):
    """Advances level to OPTIONS and stores selected_dimension when a dimension with a code list is opened."""
    _mock_open_item_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_DIMENSIONS
    tui.filtered_items = [SAMPLE_DIMENSIONS[0]]
    tui._open_item_by_index(0)
    assert tui.level == ONSExplorerTUI.LEVEL_OPTIONS
    assert tui.selected_dimension is SAMPLE_DIMENSIONS[0]


def test_open_item_dimensions_no_code_list_sets_status(tui):
    """Stays at DIMENSIONS level when the dimension has no code list link."""
    _mock_open_item_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_DIMENSIONS
    tui.filtered_items = [{"name": "agg", "id": "agg", "label": "Agg", "links": {}}]
    tui._open_item_by_index(0)
    assert tui.level == ONSExplorerTUI.LEVEL_DIMENSIONS


def test_open_item_options_level_updates_series_key(tui):
    """Updates series_key and returns to DIMENSIONS level when a non-time option is selected."""
    _mock_open_item_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_OPTIONS
    tui.selected_dimension = SAMPLE_DIMENSIONS[0]  # "aggregate", not time dim
    tui.filtered_items = [{"code": "cpih1dim1A0", "label": "All items"}]
    tui._open_item_by_index(0)
    assert tui.series_key.get("aggregate") == "cpih1dim1A0"
    assert tui.level == ONSExplorerTUI.LEVEL_DIMENSIONS


def test_open_item_options_time_dimension_not_added_to_series_key(tui):
    """Does not add a time-dimension option to series_key."""
    _mock_open_item_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_OPTIONS
    tui.selected_dimension = SAMPLE_DIMENSIONS[1]  # "time" dimension
    tui.filtered_items = [{"code": "jan-24", "label": "Jan 2024"}]
    tui._open_item_by_index(0)
    assert "time" not in tui.series_key


def test_open_item_options_unchanged_code_sets_status(tui):
    """Calls _set_status with 'unchanged' when the selected option code is already in series_key."""
    _mock_open_item_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_OPTIONS
    tui.selected_dimension = SAMPLE_DIMENSIONS[0]
    tui.series_key = {"aggregate": "cpih1dim1A0"}
    tui.filtered_items = [{"code": "cpih1dim1A0", "label": "All items"}]
    tui._open_item_by_index(0)
    call_msg = tui._set_status.call_args[0][0]
    assert "unchanged" in call_msg


def _mock_action_side_effects(tui):
    tui._clear_filter = MagicMock()
    tui._update_path = MagicMock()
    tui._update_series_key_panel = MagicMock()
    tui._refresh_current_level = MagicMock()
    tui._set_status = MagicMock()


def test_action_go_back_at_datasets_sets_status(tui):
    """Calls _set_status and stays at DATASETS level when already at the top level."""
    _mock_action_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_DATASETS
    tui.action_go_back()
    tui._set_status.assert_called_once()
    assert tui.level == ONSExplorerTUI.LEVEL_DATASETS


def test_action_go_back_from_editions(tui):
    """Returns to DATASETS level and clears selected_dataset_id when going back from EDITIONS."""
    _mock_action_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    tui.selected_dataset_id = "cpih01"
    tui.action_go_back()
    assert tui.level == ONSExplorerTUI.LEVEL_DATASETS
    assert tui.selected_dataset_id is None


def test_action_go_back_from_versions_when_edition_skipped(tui):
    """Skips EDITIONS and returns to DATASETS when edition_step_skipped is True."""
    _mock_action_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_VERSIONS
    tui.edition_step_skipped = True
    tui.selected_dataset_id = "cpih01"
    tui.selected_edition = "time-series"
    tui.action_go_back()
    assert tui.level == ONSExplorerTUI.LEVEL_DATASETS
    assert tui.edition_step_skipped is False


def test_action_go_back_from_versions_normal(tui):
    """Returns to EDITIONS level when going back from VERSIONS normally."""
    _mock_action_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_VERSIONS
    tui.edition_step_skipped = False
    tui.action_go_back()
    assert tui.level == ONSExplorerTUI.LEVEL_EDITIONS


def test_action_go_back_from_dimensions(tui):
    """Returns to VERSIONS level when going back from DIMENSIONS."""
    _mock_action_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_DIMENSIONS
    tui.action_go_back()
    assert tui.level == ONSExplorerTUI.LEVEL_VERSIONS


def test_action_go_back_from_options(tui):
    """Returns to DIMENSIONS level and clears selected_dimension when going back from OPTIONS."""
    _mock_action_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_OPTIONS
    tui.action_go_back()
    assert tui.level == ONSExplorerTUI.LEVEL_DIMENSIONS
    assert tui.selected_dimension is None


def test_action_clear_series_key_clears_state(tui):
    """Clears series_key and last_series_update when action_clear_series_key is called."""
    tui._update_series_key_panel = MagicMock()
    tui._set_status = MagicMock()
    tui._refresh_current_level = MagicMock()

    tui.series_key = {"aggregate": "cpih1dim1A0"}
    tui.last_series_update = ("aggregate", "cpih1dim1A0")
    tui.action_clear_series_key()
    assert tui.series_key == {}
    assert tui.last_series_update is None


# _load_level_worker is decorated with @work(thread=True). Calling __wrapped__
# bypasses the worker scheduler so we can run the body synchronously, with
# call_from_thread stubbed to invoke callbacks inline.
WORKER = ONSExplorerTUI._load_level_worker.__wrapped__


def _stub_thread_dispatch(tui):
    """Make call_from_thread run the callback inline so we can assert on side effects."""
    tui.call_from_thread = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    tui._on_level_loaded = MagicMock()
    tui._on_level_load_failed = MagicMock()
    tui._set_status = MagicMock()
    tui._log_loading = MagicMock()


def test_worker_datasets_skip_time_series_check(tui, explorer):
    """LEVEL_DATASETS with skip_time_series_check returns datasets tagged 'unknown'."""
    _stub_thread_dispatch(tui)
    tui.skip_time_series_check = True
    explorer.list_datasets = MagicMock(return_value=[{"id": "cpih01"}])

    WORKER(
        tui,
        level=ONSExplorerTUI.LEVEL_DATASETS,
        dataset_id=None,
        edition=None,
        version=None,
        dimension=None,
    )

    tui._on_level_loaded.assert_called_once()
    level, items = tui._on_level_loaded.call_args[0]
    assert level == ONSExplorerTUI.LEVEL_DATASETS
    assert items == [{"id": "cpih01", "has_time_series": "unknown"}]


def test_worker_datasets_with_time_series_check(tui, explorer):
    """LEVEL_DATASETS without skip flag fetches editions per dataset and tags has_time_series."""
    _stub_thread_dispatch(tui)
    tui.skip_time_series_check = False
    tui.time_series_only = False
    explorer.list_datasets = MagicMock(return_value=[{"id": "cpih01"}, {"id": "ashe"}])
    explorer.list_editions = MagicMock(
        side_effect=[
            [{"edition": "time-series"}],
            [{"edition": "2021"}],
        ]
    )

    WORKER(
        tui,
        level=ONSExplorerTUI.LEVEL_DATASETS,
        dataset_id=None,
        edition=None,
        version=None,
        dimension=None,
    )

    _, items = tui._on_level_loaded.call_args[0]
    assert items[0]["has_time_series"] is True
    assert items[1]["has_time_series"] is False


def test_worker_datasets_time_series_only_filters_out(tui, explorer):
    """LEVEL_DATASETS with time_series_only excludes datasets without a time-series edition."""
    _stub_thread_dispatch(tui)
    tui.skip_time_series_check = False
    tui.time_series_only = True
    explorer.list_datasets = MagicMock(return_value=[{"id": "cpih01"}, {"id": "ashe"}])
    explorer.list_editions = MagicMock(
        side_effect=[
            [{"edition": "time-series"}],
            [{"edition": "2021"}],
        ]
    )

    WORKER(
        tui,
        level=ONSExplorerTUI.LEVEL_DATASETS,
        dataset_id=None,
        edition=None,
        version=None,
        dimension=None,
    )

    _, items = tui._on_level_loaded.call_args[0]
    assert [i["id"] for i in items] == ["cpih01"]


def test_worker_datasets_progress_bar_emitted(tui, explorer):
    """LEVEL_DATASETS emits a status update at the final dataset (idx == total)."""
    _stub_thread_dispatch(tui)
    tui.skip_time_series_check = False
    tui.time_series_only = False
    explorer.list_datasets = MagicMock(return_value=[{"id": f"d{i}"} for i in range(3)])
    explorer.list_editions = MagicMock(return_value=[{"edition": "time-series"}])

    WORKER(
        tui,
        level=ONSExplorerTUI.LEVEL_DATASETS,
        dataset_id=None,
        edition=None,
        version=None,
        dimension=None,
    )

    # Final tick (idx == total == 3) emits the bar-formatted message.
    status_messages = [c.args[0] for c in tui._set_status.call_args_list]
    assert any("3/3" in m for m in status_messages)


def test_worker_editions_empty_dataset_id(tui):
    """LEVEL_EDITIONS with no dataset_id returns an empty list."""
    _stub_thread_dispatch(tui)
    WORKER(
        tui,
        level=ONSExplorerTUI.LEVEL_EDITIONS,
        dataset_id=None,
        edition=None,
        version=None,
        dimension=None,
    )
    _, items = tui._on_level_loaded.call_args[0]
    assert items == []


def test_worker_editions_annotates_time_series_support(tui, explorer):
    """LEVEL_EDITIONS annotates time-series editions with __series_key_supported metadata."""
    _stub_thread_dispatch(tui)
    explorer.list_editions = MagicMock(return_value=[{"edition": "time-series"}])
    tui._resolve_series_key_support_for_dataset = MagicMock(
        return_value=(True, None, "mmm-yy", "MS")
    )

    WORKER(
        tui,
        level=ONSExplorerTUI.LEVEL_EDITIONS,
        dataset_id="cpih01",
        edition=None,
        version=None,
        dimension=None,
    )

    _, items = tui._on_level_loaded.call_args[0]
    assert items[0]["__series_key_supported"] is True
    assert items[0]["__resolved_frequency"] == "MS"


def test_worker_versions_empty_when_missing_args(tui):
    """LEVEL_VERSIONS without dataset_id/edition returns []."""
    _stub_thread_dispatch(tui)
    WORKER(
        tui,
        level=ONSExplorerTUI.LEVEL_VERSIONS,
        dataset_id=None,
        edition="time-series",
        version=None,
        dimension=None,
    )
    _, items = tui._on_level_loaded.call_args[0]
    assert items == []


def test_worker_versions_calls_explorer(tui, explorer):
    """LEVEL_VERSIONS delegates to explorer.list_versions when args are present."""
    _stub_thread_dispatch(tui)
    explorer.list_versions = MagicMock(return_value=SAMPLE_VERSIONS)

    WORKER(
        tui,
        level=ONSExplorerTUI.LEVEL_VERSIONS,
        dataset_id="cpih01",
        edition="time-series",
        version=None,
        dimension=None,
    )

    explorer.list_versions.assert_called_once_with("cpih01", "time-series")
    _, items = tui._on_level_loaded.call_args[0]
    assert items == SAMPLE_VERSIONS


def test_worker_dimensions_filters_time_dimension(tui, explorer):
    """LEVEL_DIMENSIONS filters out time dimensions when show_time_dimension is False."""
    _stub_thread_dispatch(tui)
    tui.show_time_dimension = False
    explorer.list_dimensions = MagicMock(return_value=SAMPLE_DIMENSIONS)

    WORKER(
        tui,
        level=ONSExplorerTUI.LEVEL_DIMENSIONS,
        dataset_id="cpih01",
        edition="time-series",
        version="3",
        dimension=None,
    )

    _, items = tui._on_level_loaded.call_args[0]
    assert all(i.get("name") != "time" for i in items)


def test_worker_dimensions_keeps_time_when_flag_on(tui, explorer):
    """LEVEL_DIMENSIONS keeps time dimensions when show_time_dimension is True."""
    _stub_thread_dispatch(tui)
    tui.show_time_dimension = True
    explorer.list_dimensions = MagicMock(return_value=SAMPLE_DIMENSIONS)

    WORKER(
        tui,
        level=ONSExplorerTUI.LEVEL_DIMENSIONS,
        dataset_id="cpih01",
        edition="time-series",
        version="3",
        dimension=None,
    )

    _, items = tui._on_level_loaded.call_args[0]
    assert any(i.get("name") == "time" for i in items)


def test_worker_dimensions_empty_when_missing_args(tui):
    """LEVEL_DIMENSIONS returns [] when dataset_id/edition/version are missing."""
    _stub_thread_dispatch(tui)
    WORKER(
        tui,
        level=ONSExplorerTUI.LEVEL_DIMENSIONS,
        dataset_id="cpih01",
        edition="time-series",
        version=None,
        dimension=None,
    )
    _, items = tui._on_level_loaded.call_args[0]
    assert items == []


def test_worker_options_with_code_list(tui, explorer):
    """LEVEL_OPTIONS calls list_dimension_options and forwards the items."""
    _stub_thread_dispatch(tui)
    explorer.list_dimension_options = MagicMock(
        return_value=("time-series", SAMPLE_CODES)
    )

    WORKER(
        tui,
        level=ONSExplorerTUI.LEVEL_OPTIONS,
        dataset_id="cpih01",
        edition="time-series",
        version="3",
        dimension=SAMPLE_DIMENSIONS[0],
    )

    explorer.list_dimension_options.assert_called_once()
    _, items = tui._on_level_loaded.call_args[0]
    assert items == SAMPLE_CODES


def test_worker_options_progress_callback_invoked(tui, explorer):
    """LEVEL_OPTIONS forwards progress events via _set_status / _log_loading."""
    _stub_thread_dispatch(tui)

    def fake_list_options(*, code_list_id, code_list_edition, progress_callback):
        progress_callback(2, 50)
        return ("time-series", SAMPLE_CODES)

    explorer.list_dimension_options = MagicMock(side_effect=fake_list_options)

    WORKER(
        tui,
        level=ONSExplorerTUI.LEVEL_OPTIONS,
        dataset_id="cpih01",
        edition="time-series",
        version="3",
        dimension=SAMPLE_DIMENSIONS[0],
    )

    assert any("page 2" in c.args[0] for c in tui._set_status.call_args_list)


def test_worker_options_missing_code_list_returns_empty(tui, explorer):
    """LEVEL_OPTIONS returns [] when the dimension has no code list id."""
    _stub_thread_dispatch(tui)
    bad_dim = {"name": "agg", "id": "agg", "links": {}}

    WORKER(
        tui,
        level=ONSExplorerTUI.LEVEL_OPTIONS,
        dataset_id="cpih01",
        edition="time-series",
        version="3",
        dimension=bad_dim,
    )

    _, items = tui._on_level_loaded.call_args[0]
    assert items == []


def test_worker_options_empty_when_missing_args(tui):
    """LEVEL_OPTIONS returns [] when one of the required args is missing."""
    _stub_thread_dispatch(tui)
    WORKER(
        tui,
        level=ONSExplorerTUI.LEVEL_OPTIONS,
        dataset_id="cpih01",
        edition="time-series",
        version=None,
        dimension=SAMPLE_DIMENSIONS[0],
    )
    _, items = tui._on_level_loaded.call_args[0]
    assert items == []


def test_worker_unknown_level_returns_empty(tui):
    """Unknown level falls through and returns []."""
    _stub_thread_dispatch(tui)
    WORKER(
        tui,
        level="bogus",
        dataset_id=None,
        edition=None,
        version=None,
        dimension=None,
    )
    _, items = tui._on_level_loaded.call_args[0]
    assert items == []


def test_worker_explorer_exception_calls_failed(tui, explorer):
    """An exception inside the worker body routes to _on_level_load_failed."""
    _stub_thread_dispatch(tui)
    explorer.list_datasets = MagicMock(side_effect=RuntimeError("boom"))
    tui.skip_time_series_check = True

    WORKER(
        tui,
        level=ONSExplorerTUI.LEVEL_DATASETS,
        dataset_id=None,
        edition=None,
        version=None,
        dimension=None,
    )

    tui._on_level_loaded.assert_not_called()
    tui._on_level_load_failed.assert_called_once()
    level, message = tui._on_level_load_failed.call_args[0]
    assert level == ONSExplorerTUI.LEVEL_DATASETS
    assert "boom" in message


def test_on_level_loaded_editions_only_blocked_ts(tui):
    """Single time-series edition that's blocked sets a 'blocked' status, no auto-skip."""
    tui._stop_loading = MagicMock()
    tui._finish_startup = MagicMock()
    tui._apply_filter = MagicMock()
    tui._set_status = MagicMock()

    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    blocked = {
        "edition": "time-series",
        "__series_key_supported": False,
        "__series_key_block_reason": "Unsupported time dim",
    }
    tui._on_level_loaded(ONSExplorerTUI.LEVEL_EDITIONS, [blocked])

    msg = tui._set_status.call_args[0][0]
    assert "blocked" in msg.lower()
    assert tui.level == ONSExplorerTUI.LEVEL_EDITIONS  # no auto-skip


def test_on_level_loaded_editions_time_series_only_with_blocked_count(tui):
    """time_series_only mode reports the blocked count when some time-series editions are blocked."""
    tui._stop_loading = MagicMock()
    tui._finish_startup = MagicMock()
    tui._apply_filter = MagicMock()
    tui._set_status = MagicMock()

    tui.time_series_only = True
    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    items = [
        {"edition": "time-series", "__series_key_supported": True},
        {
            "edition": "time-series",
            "__series_key_supported": False,
            "__series_key_block_reason": "x",
        },
    ]
    tui._on_level_loaded(ONSExplorerTUI.LEVEL_EDITIONS, items)

    msgs = [c.args[0] for c in tui._set_status.call_args_list]
    assert any("blocked" in m for m in msgs)


def test_on_level_loaded_editions_includes_other_editions_message(tui):
    """time_series_only=False shows the 'pinned first' message when a TS edition exists."""
    tui._stop_loading = MagicMock()
    tui._finish_startup = MagicMock()
    tui._apply_filter = MagicMock()
    tui._set_status = MagicMock()

    tui.time_series_only = False
    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    items = [
        {"edition": "time-series", "__series_key_supported": True},
        {"edition": "2021"},
    ]
    tui._on_level_loaded(ONSExplorerTUI.LEVEL_EDITIONS, items)

    msg = tui._set_status.call_args[0][0]
    assert "pinned" in msg.lower() or "reference-only" in msg.lower()


def test_on_level_loaded_datasets_skip_message(tui):
    """skip_time_series_check + time_series_only emits a 'Skipped' status note."""
    tui._stop_loading = MagicMock()
    tui._finish_startup = MagicMock()
    tui._apply_filter = MagicMock()
    tui._set_status = MagicMock()

    tui.skip_time_series_check = True
    tui.time_series_only = True
    tui.level = ONSExplorerTUI.LEVEL_DATASETS
    tui._on_level_loaded(ONSExplorerTUI.LEVEL_DATASETS, SAMPLE_DATASETS)

    msg = tui._set_status.call_args[0][0]
    assert "Skipped" in msg


def test_on_level_loaded_versions_generic_message(tui):
    """Generic levels get a 'Loaded N item(s)' message."""
    tui._stop_loading = MagicMock()
    tui._apply_filter = MagicMock()
    tui._set_status = MagicMock()

    tui.level = ONSExplorerTUI.LEVEL_VERSIONS
    tui._on_level_loaded(ONSExplorerTUI.LEVEL_VERSIONS, SAMPLE_VERSIONS)

    msg = tui._set_status.call_args[0][0]
    assert "versions" in msg
    assert str(len(SAMPLE_VERSIONS)) in msg


def test_open_item_editions_empty_edition_field(tui):
    """An edition item with no 'edition' field is rejected with a status update."""
    _mock_open_item_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    tui.filtered_items = [{"edition": ""}]
    tui._open_item_by_index(0)
    assert tui.level == ONSExplorerTUI.LEVEL_EDITIONS
    tui._set_status.assert_called()


def test_open_item_options_no_dimension_set_status(tui):
    """OPTIONS with selected_dimension=None sets status and stays at OPTIONS level."""
    _mock_open_item_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_OPTIONS
    tui.selected_dimension = None
    tui.filtered_items = [{"code": "x"}]
    tui._open_item_by_index(0)
    tui._set_status.assert_called()


def test_open_item_options_updates_existing_value(tui):
    """Updating an existing series_key value emits an 'Updated' status."""
    _mock_open_item_side_effects(tui)
    tui.level = ONSExplorerTUI.LEVEL_OPTIONS
    tui.selected_dimension = SAMPLE_DIMENSIONS[0]
    tui.series_key = {"aggregate": "old"}
    tui.filtered_items = [{"code": "new", "label": "New"}]
    tui._open_item_by_index(0)
    assert tui.series_key["aggregate"] == "new"
    msg = tui._set_status.call_args[0][0]
    assert "Updated" in msg


def test_main_runs_app_and_returns_zero():
    """main() builds the app, runs it, and returns the app's return code."""
    with (
        patch("macrotrace.ons_cli.tui.ONSExplorerClient") as MockClient,
        patch("macrotrace.ons_cli.tui.ONSExplorerTUI") as MockApp,
        patch("macrotrace.ons_cli.tui.signal.signal"),
    ):
        MockClient.return_value = MagicMock()
        app_instance = MagicMock()
        app_instance.return_code = 0
        app_instance.fatal_traceback_printed = False
        MockApp.return_value = app_instance

        from macrotrace.ons_cli.tui import main

        rc = main(["--no-cache"])

    assert rc == 0
    app_instance.run.assert_called_once()


def test_main_clear_cache_invokes_client_clear_cache():
    """--clear-cache calls ONSExplorerClient.clear_cache before running the app."""
    with (
        patch("macrotrace.ons_cli.tui.ONSExplorerClient") as MockClient,
        patch("macrotrace.ons_cli.tui.ONSExplorerTUI") as MockApp,
        patch("macrotrace.ons_cli.tui.signal.signal"),
    ):
        client_instance = MagicMock()
        MockClient.return_value = client_instance
        app_instance = MagicMock()
        app_instance.return_code = 0
        app_instance.fatal_traceback_printed = False
        MockApp.return_value = app_instance

        from macrotrace.ons_cli.tui import main

        main(["--clear-cache"])

    client_instance.clear_cache.assert_called_once()


def test_main_keyboard_interrupt_returns_130():
    """KeyboardInterrupt during app.run propagates as exit code 130."""
    with (
        patch("macrotrace.ons_cli.tui.ONSExplorerClient") as MockClient,
        patch("macrotrace.ons_cli.tui.ONSExplorerTUI") as MockApp,
        patch("macrotrace.ons_cli.tui.signal.signal"),
    ):
        MockClient.return_value = MagicMock()
        app_instance = MagicMock()
        app_instance.run.side_effect = KeyboardInterrupt()
        MockApp.return_value = app_instance

        from macrotrace.ons_cli.tui import main

        rc = main([])

    assert rc == 130


def test_main_unhandled_exception_returns_one(capsys):
    """An unexpected exception during app.run is logged and returns exit code 1."""
    with (
        patch("macrotrace.ons_cli.tui.ONSExplorerClient") as MockClient,
        patch("macrotrace.ons_cli.tui.ONSExplorerTUI") as MockApp,
        patch("macrotrace.ons_cli.tui.signal.signal"),
    ):
        MockClient.return_value = MagicMock()
        app_instance = MagicMock()
        app_instance.run.side_effect = RuntimeError("boom")
        MockApp.return_value = app_instance

        from macrotrace.ons_cli.tui import main

        rc = main([])

    assert rc == 1
    err = capsys.readouterr().err
    assert "boom" in err


def test_main_nonzero_return_code_with_internal_exception(capsys):
    """A non-zero return_code with an _exception attribute prints the traceback."""
    with (
        patch("macrotrace.ons_cli.tui.ONSExplorerClient") as MockClient,
        patch("macrotrace.ons_cli.tui.ONSExplorerTUI") as MockApp,
        patch("macrotrace.ons_cli.tui.signal.signal"),
    ):
        MockClient.return_value = MagicMock()
        app_instance = MagicMock()
        app_instance.return_code = 2
        app_instance.fatal_traceback_printed = False
        app_instance._exception = ValueError("inner failure")
        MockApp.return_value = app_instance

        from macrotrace.ons_cli.tui import main

        rc = main([])

    assert rc == 2
    err = capsys.readouterr().err
    assert "internal exception" in err


def test_main_nonzero_return_code_without_exception(capsys):
    """A non-zero return_code with no _exception prints a generic exit-code message."""
    with (
        patch("macrotrace.ons_cli.tui.ONSExplorerClient") as MockClient,
        patch("macrotrace.ons_cli.tui.ONSExplorerTUI") as MockApp,
        patch("macrotrace.ons_cli.tui.signal.signal"),
    ):
        MockClient.return_value = MagicMock()
        app_instance = MagicMock()
        app_instance.return_code = 2
        app_instance.fatal_traceback_printed = False
        app_instance._exception = None
        MockApp.return_value = app_instance

        from macrotrace.ons_cli.tui import main

        rc = main([])

    assert rc == 2
    err = capsys.readouterr().err
    assert "non-zero code 2" in err


# Methods that touch self.query_one(...) need a mounted Textual app. We
# sidestep that by stubbing query_one with a per-selector MagicMock store.
def _patch_query_one(tui):
    """Replace tui.query_one with a factory that returns a MagicMock per selector."""
    widgets: Dict[str, MagicMock] = {}

    def factory(selector, _widget_type=None):
        if selector not in widgets:
            widget = MagicMock()
            widget.size.width = 100
            widget.value = ""
            widgets[selector] = widget
        return widgets[selector]

    tui.query_one = factory
    return widgets


def test_clear_filter_resets_input(tui):
    """_clear_filter sets the filter Input value back to an empty string."""
    widgets = _patch_query_one(tui)
    widgets.setdefault("#filter", MagicMock()).value = "stale"
    tui._clear_filter()
    assert tui.query_one("#filter").value == ""


def test_set_status_when_idle_updates_status_widget(tui):
    """_set_status writes to #status when the loading spinner is not active."""
    _patch_query_one(tui)
    tui.startup_complete = True
    tui.loading_active = False
    tui._set_status("ready")
    assert tui.status_message == "ready"
    assert tui.quit_requested_once is False


def test_set_status_during_loading_routes_to_loading_message(tui):
    """While loading is active, _set_status updates loading_message instead of status_message."""
    _patch_query_one(tui)
    tui.loading_active = True
    tui._set_status("hold on")
    assert tui.loading_message == "hold on"


def test_start_loading_initializes_state(tui):
    """_start_loading resets the spinner state and stores the message."""
    _patch_query_one(tui)
    tui.loading_logs = ["leftover"]
    tui._render_loading_or_status = MagicMock()
    tui._start_loading("Loading datasets")
    assert tui.loading_active is True
    assert tui.loading_message == "Loading datasets"
    assert tui.loading_frame == 0
    assert tui.loading_logs == []


def test_stop_loading_clears_active(tui):
    """_stop_loading flips loading_active to False."""
    _patch_query_one(tui)
    tui.loading_active = True
    tui._stop_loading()
    assert tui.loading_active is False


def test_render_loading_or_status_during_startup(tui):
    """While not started up, render writes the loading text into #startup_loading."""
    widgets = _patch_query_one(tui)
    tui.startup_complete = False
    tui.loading_active = True
    tui.loading_message = "fetching"
    tui.loading_started_at = time.monotonic()
    tui._render_loading_or_status()
    widgets["#startup_loading"].update.assert_called()


def test_render_loading_or_status_post_startup(tui):
    """After startup, status messages render to #status."""
    widgets = _patch_query_one(tui)
    tui.startup_complete = True
    tui.loading_active = False
    tui.status_message = "ok"
    tui._render_loading_or_status()
    widgets["#status"].update.assert_called_with("ok")


def test_render_loading_or_status_appends_rate_limit(tui):
    """Rate-limit suffix is appended to the rendered status text."""
    widgets = _patch_query_one(tui)
    tui.startup_complete = True
    tui.loading_active = False
    tui.status_message = "ok"
    tui.rate_limit_until = time.monotonic() + 5.0
    tui.rate_limit_endpoint = "datasets"
    tui._render_loading_or_status()
    rendered = widgets["#status"].update.call_args[0][0]
    assert "datasets" in rendered


def test_tick_loading_calls_render(tui):
    """_tick_loading delegates to _render_loading_or_status."""
    tui._render_loading_or_status = MagicMock()
    tui._tick_loading()
    tui._render_loading_or_status.assert_called_once()


def test_set_display_toggles_widget_display(tui):
    """_set_display writes show/hide to widget.display."""
    widgets = _patch_query_one(tui)
    tui._set_display("filter", False)
    assert widgets["#filter"].display is False


def test_set_main_ui_visible_toggles_widgets(tui):
    """_set_main_ui_visible flips display on every main-UI widget plus #startup_loading."""
    widgets = _patch_query_one(tui)
    tui._set_main_ui_visible(True)
    for wid in ("breadcrumbs", "filter", "main", "series_bar", "status", "footer"):
        assert widgets[f"#{wid}"].display is True
    assert widgets["#startup_loading"].display is False


def test_finish_startup_marks_complete(tui):
    """_finish_startup sets startup_complete and reveals the main UI."""
    _patch_query_one(tui)
    tui._finish_startup()
    assert tui.startup_complete is True


def test_finish_startup_idempotent(tui):
    """Calling _finish_startup a second time is a no-op."""
    tui.startup_complete = True
    tui._set_main_ui_visible = MagicMock()
    tui._finish_startup()
    tui._set_main_ui_visible.assert_not_called()


def test_update_path_at_datasets_level(tui):
    """_update_path disables the Datasets crumb when at LEVEL_DATASETS."""
    widgets = _patch_query_one(tui)
    tui.level = ONSExplorerTUI.LEVEL_DATASETS
    tui._update_path()
    assert widgets["#crumb_datasets"].disabled is True


def test_update_path_with_full_selection(tui):
    """_update_path labels and shows every crumb when a dimension is selected."""
    widgets = _patch_query_one(tui)
    tui.level = ONSExplorerTUI.LEVEL_OPTIONS
    tui.selected_dataset_id = "cpih01"
    tui.selected_edition = "time-series"
    tui.selected_version = "3"
    tui.selected_dimension = SAMPLE_DIMENSIONS[0]
    tui._update_path()
    assert "cpih01" in str(widgets["#crumb_dataset"].label)
    assert "time-series" in str(widgets["#crumb_edition"].label)


def test_update_series_key_panel_no_dataset(tui):
    """Without a selected dataset, the panel shows the placeholder text."""
    widgets = _patch_query_one(tui)
    tui._update_series_key_panel()
    rendered = widgets["#series_key"].update.call_args[0][0]
    assert "Select a dataset" in rendered


def test_update_series_key_panel_with_selection(tui):
    """With a dataset selected, the panel shows the constructed series snippet."""
    widgets = _patch_query_one(tui)
    tui.selected_dataset_id = "cpih01"
    tui.series_key = {"agg": "A0"}
    tui.last_series_update = ("agg", "A0")
    tui._update_series_key_panel()
    rendered = widgets["#series_key"].update.call_args[0][0]
    assert "MTTimeSeries" in rendered
    assert "Last Updated" in rendered


def test_action_copy_series_no_snippet(tui):
    """action_copy_series tells the user when there's nothing to copy."""
    tui._set_status = MagicMock()
    tui.action_copy_series()
    msg = tui._set_status.call_args[0][0]
    assert "No constructed series" in msg


def test_action_copy_series_success(tui):
    """action_copy_series reports success when the clipboard call succeeds."""
    tui._set_status = MagicMock()
    tui.selected_dataset_id = "cpih01"
    tui._copy_to_clipboard = MagicMock(return_value=True)
    tui.action_copy_series()
    msg = tui._set_status.call_args[0][0]
    assert "Copied" in msg


def test_action_copy_series_clipboard_unavailable(tui):
    """action_copy_series reports unavailability when no clipboard is found."""
    tui._set_status = MagicMock()
    tui.selected_dataset_id = "cpih01"
    tui._copy_to_clipboard = MagicMock(return_value=False)
    tui.action_copy_series()
    msg = tui._set_status.call_args[0][0]
    assert "Clipboard unavailable" in msg


def test_show_series_key_in_detail_no_snippet(tui):
    """_show_series_key_in_detail shows a placeholder when no dataset is selected."""
    widgets = _patch_query_one(tui)
    tui._set_status = MagicMock()
    tui._show_series_key_in_detail()
    widgets["#detail"].clear.assert_called()
    widgets["#detail"].write.assert_called()


def test_show_series_key_in_detail_with_snippet(tui):
    """_show_series_key_in_detail writes the snippet plus series_key when present."""
    widgets = _patch_query_one(tui)
    tui._set_status = MagicMock()
    tui.selected_dataset_id = "cpih01"
    tui.series_key = {"agg": "A0"}
    tui._show_series_key_in_detail()
    writes = [c.args[0] for c in widgets["#detail"].write.call_args_list]
    assert any("MTTimeSeries" in str(w) for w in writes)


def test_refresh_current_level_dispatches_worker(tui):
    """_refresh_current_level updates path, starts loading, and dispatches the worker."""
    tui._update_path = MagicMock()
    tui._start_loading = MagicMock()
    tui._load_level_worker = MagicMock()
    tui._refresh_current_level()
    tui._update_path.assert_called_once()
    tui._start_loading.assert_called_once()
    tui._load_level_worker.assert_called_once()


def test_apply_filter_no_query(tui):
    """_apply_filter without a query keeps every current item."""
    widgets = _patch_query_one(tui)
    widgets["#filter"] = MagicMock()
    widgets["#filter"].value = ""
    tui._render_option_list = MagicMock()
    tui.current_items = [{"id": "a"}, {"id": "b"}]
    tui._apply_filter()
    assert tui.filtered_items == [{"id": "a"}, {"id": "b"}]


def test_apply_filter_filters_by_query(tui):
    """_apply_filter narrows current_items by case-insensitive substring match."""
    widgets = _patch_query_one(tui)
    widgets["#filter"] = MagicMock()
    widgets["#filter"].value = "cpi"
    tui._render_option_list = MagicMock()
    tui.level = ONSExplorerTUI.LEVEL_DATASETS
    tui.current_items = [
        {"id": "cpih01", "title": "CPIH", "description": ""},
        {"id": "gdp", "title": "GDP", "description": ""},
    ]
    tui._apply_filter()
    assert tui.filtered_items == [tui.current_items[0]]


def test_render_option_list_with_items(tui):
    """_render_option_list adds an option per filtered item and highlights index 0."""
    widgets = _patch_query_one(tui)
    tui._update_detail_for_index = MagicMock()
    tui.level = ONSExplorerTUI.LEVEL_DATASETS
    tui.filtered_items = [
        {"id": "cpih01", "title": "CPIH", "description": ""},
        {"id": "gdp", "title": "GDP", "description": ""},
    ]
    tui._render_option_list()
    assert widgets["#items"].add_option.call_count == 2
    tui._update_detail_for_index.assert_called_with(0)


def test_render_option_list_empty(tui):
    """_render_option_list clears the detail pane and sets a 'no results' status when empty."""
    _patch_query_one(tui)
    tui._clear_detail = MagicMock()
    tui._set_status = MagicMock()
    tui.filtered_items = []
    tui._render_option_list()
    tui._clear_detail.assert_called_once()
    tui._set_status.assert_called_once()


def test_clear_detail_clears_richlog(tui):
    """_clear_detail clears the #detail RichLog."""
    widgets = _patch_query_one(tui)
    tui._clear_detail()
    widgets["#detail"].clear.assert_called_once()


def test_update_detail_for_index_out_of_range(tui):
    """An out-of-range index is silently ignored."""
    _patch_query_one(tui)
    tui.filtered_items = []
    tui._update_detail_for_index(0)  # no-op, no exception


def test_update_detail_for_index_editions_with_blocked_ts(tui):
    """Edition-level detail writes a 'blocked' note when the TS edition isn't supported."""
    widgets = _patch_query_one(tui)
    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    tui.current_items = [{"edition": "time-series"}]
    tui.filtered_items = [
        {
            "edition": "time-series",
            "__series_key_supported": False,
            "__series_key_block_reason": "bad type",
        }
    ]
    tui._update_detail_for_index(0)
    writes = [c.args[0] for c in widgets["#detail"].write.call_args_list]
    assert any("blocked" in str(w).lower() for w in writes)


def test_update_detail_for_index_editions_supported_ts(tui):
    """Edition-level detail writes the resolved frequency when TS is supported."""
    widgets = _patch_query_one(tui)
    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    tui.current_items = [{"edition": "time-series"}]
    tui.filtered_items = [
        {
            "edition": "time-series",
            "__series_key_supported": True,
            "__resolved_frequency": "MS",
        }
    ]
    tui._update_detail_for_index(0)
    writes = [str(c.args[0]) for c in widgets["#detail"].write.call_args_list]
    assert any("frequency" in w.lower() for w in writes)


def test_update_detail_for_index_editions_no_time_series(tui):
    """Edition-level detail explains 'no time-series edition' when none exists."""
    widgets = _patch_query_one(tui)
    tui.level = ONSExplorerTUI.LEVEL_EDITIONS
    tui.current_items = [{"edition": "2021"}]
    tui.filtered_items = [{"edition": "2021"}]
    tui._update_detail_for_index(0)
    writes = [str(c.args[0]) for c in widgets["#detail"].write.call_args_list]
    assert any("No time-series" in w for w in writes)


def test_update_detail_for_index_options_with_dimension(tui):
    """Options-level detail includes the active dimension name."""
    widgets = _patch_query_one(tui)
    tui.level = ONSExplorerTUI.LEVEL_OPTIONS
    tui.selected_dimension = SAMPLE_DIMENSIONS[0]
    tui.filtered_items = [{"code": "X", "label": "x"}]
    tui._update_detail_for_index(0)
    writes = [str(c.args[0]) for c in widgets["#detail"].write.call_args_list]
    assert any("aggregate" in w for w in writes)


def test_on_input_changed_filter_reapplies(tui):
    """A change on the #filter input triggers _apply_filter."""
    tui._apply_filter = MagicMock()
    event = MagicMock()
    event.input.id = "filter"
    tui.on_input_changed(event)
    tui._apply_filter.assert_called_once()


def test_on_input_changed_other_input_ignored(tui):
    """Changes on other inputs are ignored."""
    tui._apply_filter = MagicMock()
    event = MagicMock()
    event.input.id = "something_else"
    tui.on_input_changed(event)
    tui._apply_filter.assert_not_called()


def _patch_button_handlers(tui):
    tui._clear_filter = MagicMock()
    tui._update_path = MagicMock()
    tui._update_series_key_panel = MagicMock()
    tui._refresh_current_level = MagicMock()


def _press(button_id):
    event = MagicMock()
    event.button.id = button_id
    return event


def test_on_button_pressed_crumb_datasets_resets_state(tui):
    """Pressing the Datasets crumb resets navigation back to LEVEL_DATASETS."""
    _patch_button_handlers(tui)
    tui.level = ONSExplorerTUI.LEVEL_OPTIONS
    tui.selected_dataset_id = "cpih01"
    tui.series_key = {"agg": "A0"}
    tui.on_button_pressed(_press("crumb_datasets"))
    assert tui.level == ONSExplorerTUI.LEVEL_DATASETS
    assert tui.selected_dataset_id is None
    assert tui.series_key == {}


def test_on_button_pressed_crumb_dataset(tui):
    """Pressing the dataset crumb returns to LEVEL_EDITIONS."""
    _patch_button_handlers(tui)
    tui.level = ONSExplorerTUI.LEVEL_VERSIONS
    tui.selected_dataset_id = "cpih01"
    tui.on_button_pressed(_press("crumb_dataset"))
    assert tui.level == ONSExplorerTUI.LEVEL_EDITIONS


def test_on_button_pressed_crumb_dataset_no_id_noop(tui):
    """Pressing the dataset crumb with no selected dataset is a no-op."""
    _patch_button_handlers(tui)
    tui.level = ONSExplorerTUI.LEVEL_VERSIONS
    tui.selected_dataset_id = None
    tui.on_button_pressed(_press("crumb_dataset"))
    tui._refresh_current_level.assert_not_called()


def test_on_button_pressed_crumb_edition(tui):
    """Pressing the edition crumb returns to LEVEL_VERSIONS."""
    _patch_button_handlers(tui)
    tui.level = ONSExplorerTUI.LEVEL_DIMENSIONS
    tui.selected_dataset_id = "cpih01"
    tui.selected_edition = "time-series"
    tui.on_button_pressed(_press("crumb_edition"))
    assert tui.level == ONSExplorerTUI.LEVEL_VERSIONS


def test_on_button_pressed_crumb_version(tui):
    """Pressing the version crumb returns to LEVEL_DIMENSIONS."""
    _patch_button_handlers(tui)
    tui.level = ONSExplorerTUI.LEVEL_OPTIONS
    tui.selected_dataset_id = "cpih01"
    tui.selected_edition = "time-series"
    tui.selected_version = "3"
    tui.on_button_pressed(_press("crumb_version"))
    assert tui.level == ONSExplorerTUI.LEVEL_DIMENSIONS


def test_on_button_pressed_crumb_dimension(tui):
    """Pressing the dimension crumb returns to LEVEL_OPTIONS."""
    _patch_button_handlers(tui)
    tui.level = ONSExplorerTUI.LEVEL_DIMENSIONS
    tui.selected_dataset_id = "cpih01"
    tui.selected_edition = "time-series"
    tui.selected_version = "3"
    tui.selected_dimension = SAMPLE_DIMENSIONS[0]
    tui.on_button_pressed(_press("crumb_dimension"))
    assert tui.level == ONSExplorerTUI.LEVEL_OPTIONS


def test_on_button_pressed_copy_series_invokes_action(tui):
    """Pressing the Copy button calls action_copy_series."""
    tui.action_copy_series = MagicMock()
    tui.on_button_pressed(_press("copy_series"))
    tui.action_copy_series.assert_called_once()


def test_on_option_list_highlighted_updates_detail(tui):
    """Highlighting an item in #items invokes _update_detail_for_index."""
    tui._update_detail_for_index = MagicMock()
    event = MagicMock()
    event.option_list.id = "items"
    event.option_index = 2
    tui.on_option_list_option_highlighted(event)
    tui._update_detail_for_index.assert_called_once_with(2)


def test_on_option_list_highlighted_other_list_ignored(tui):
    """Highlight events from other option lists are ignored."""
    tui._update_detail_for_index = MagicMock()
    event = MagicMock()
    event.option_list.id = "other"
    event.option_index = 2
    tui.on_option_list_option_highlighted(event)
    tui._update_detail_for_index.assert_not_called()


def test_on_option_list_selected_opens_item(tui):
    """Selecting an item in #items invokes _open_item_by_index."""
    tui._open_item_by_index = MagicMock()
    event = MagicMock()
    event.option_list.id = "items"
    event.option_index = 1
    tui.on_option_list_option_selected(event)
    tui._open_item_by_index.assert_called_once_with(1)


def test_on_option_list_selected_other_list_ignored(tui):
    """Selection events from other option lists are ignored."""
    tui._open_item_by_index = MagicMock()
    event = MagicMock()
    event.option_list.id = "other"
    event.option_index = 1
    tui.on_option_list_option_selected(event)
    tui._open_item_by_index.assert_not_called()


def test_action_refresh_calls_refresh_current(tui):
    """action_refresh dispatches to _refresh_current_level."""
    tui._refresh_current_level = MagicMock()
    tui.action_refresh()
    tui._refresh_current_level.assert_called_once()


def test_action_open_selected_no_highlight_sets_status(tui):
    """action_open_selected sets a status when nothing is highlighted."""
    widgets = _patch_query_one(tui)
    widgets["#items"] = MagicMock()
    widgets["#items"].highlighted = None
    tui._set_status = MagicMock()
    tui.action_open_selected()
    tui._set_status.assert_called_once()


def test_action_open_selected_with_highlight_opens_item(tui):
    """action_open_selected opens the highlighted index when one is set."""
    widgets = _patch_query_one(tui)
    widgets["#items"] = MagicMock()
    widgets["#items"].highlighted = 3
    tui._open_item_by_index = MagicMock()
    tui.action_open_selected()
    tui._open_item_by_index.assert_called_once_with(3)


def test_action_show_series_key_dispatches(tui):
    """action_show_series_key dispatches to _show_series_key_in_detail."""
    tui._show_series_key_in_detail = MagicMock()
    tui.action_show_series_key()
    tui._show_series_key_in_detail.assert_called_once()


def test_action_block_ctrl_q_sets_status(tui):
    """action_block_ctrl_q sets a status explaining how to actually quit."""
    tui._set_status = MagicMock()
    tui.action_block_ctrl_q()
    tui._set_status.assert_called_once()


def test_action_terminal_quit_first_call_requests_exit(tui):
    """The first ctrl+c request flips quit_requested_once and asks the app to exit."""
    tui._set_status = MagicMock()
    tui.exit = MagicMock()
    tui.action_terminal_quit()
    assert tui.quit_requested_once is True
    tui.exit.assert_called_once_with(return_code=130)


def test_action_terminal_quit_second_call_force_quits(tui):
    """A second ctrl+c calls _force_quit_now."""
    tui.quit_requested_once = True
    tui._force_quit_now = MagicMock()
    tui.action_terminal_quit()
    tui._force_quit_now.assert_called_once()


def test_on_resize_updates_series_key_panel(tui):
    """on_resize triggers _update_series_key_panel."""
    tui._update_series_key_panel = MagicMock()
    tui.on_resize(MagicMock())
    tui._update_series_key_panel.assert_called_once()


def test_on_key_ctrl_c_triggers_quit(tui):
    """Ctrl+C bubbling up via on_key still triggers action_terminal_quit."""
    tui.action_terminal_quit = MagicMock()
    event = MagicMock()
    event.key = "ctrl+c"
    tui.on_key(event)
    tui.action_terminal_quit.assert_called_once()
    event.stop.assert_called_once()


def test_on_key_other_key_ignored(tui):
    """Non-ctrl keys do not trigger quit."""
    tui.action_terminal_quit = MagicMock()
    event = MagicMock()
    event.key = "x"
    tui.on_key(event)
    tui.action_terminal_quit.assert_not_called()
