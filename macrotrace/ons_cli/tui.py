"""Textual ONS explorer TUI."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import textwrap
import time
import traceback
from typing import Any, Dict, List, Optional

from rich.pretty import Pretty

try:
    from textual import work
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal
    from textual.events import Key, Resize
    from textual.widgets import (
        Button,
        Footer,
        Header,
        Input,
        OptionList,
        RichLog,
        Static,
    )
    from textual.widgets.option_list import Option
except ImportError as exc:  # pragma: no cover - runtime guidance only
    raise SystemExit(
        "TUI dependencies are missing. Run `uv sync --extra ons-tui` from a repo checkout, "
        'or install the published package with `pip install "macrotrace[ons-tui]"`.'
    ) from exc

from .common import (
    DEFAULT_BASE_URL,
    DEFAULT_CACHE_EXPIRY_SECONDS,
    ONSExplorer,
    ONSExplorerClient,
    dimension_key as _dimension_key,
    dimension_label as _dimension_label,
    extract_code_list_edition as _extract_code_list_edition,
    extract_code_list_id as _extract_code_list_id,
    is_time_dimension as _is_time_dimension,
    norm_text as _norm,
    resolve_ons_frequency_from_version_metadata as _resolve_ons_frequency_from_version_metadata,
)

LOGGER = logging.getLogger("ons_explorer_tui")


class ONSExplorerTUI(App[None]):
    TITLE = "ONS Data Explorer"

    CSS = """
    Screen {
        layout: vertical;
    }

    #breadcrumbs {
        height: 3;
        padding: 0 1;
    }

    .crumb-sep {
        width: auto;
        content-align: center middle;
        padding: 0 1;
    }

    .crumb-btn {
        width: auto;
        min-width: 0;
    }

    #filter {
        margin: 0 1;
    }

    #main {
        height: 1fr;
        margin: 0 1;
    }

    #items {
        width: 42%;
        border: solid $accent;
    }

    #detail {
        width: 58%;
        border: solid $accent;
    }

    #series_bar {
        height: 7;
        margin: 0 1;
        border: solid $success;
        padding: 0 1;
    }

    #series_key {
        width: 1fr;
        content-align: left top;
        overflow-x: hidden;
        overflow-y: auto;
    }

    #copy_series {
        width: 12;
    }

    #status {
        height: 1;
        margin: 0 1;
    }

    #startup_loading {
        height: 1fr;
        margin: 0 1;
        border: solid $accent;
        content-align: center middle;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "block_ctrl_q", show=False, priority=True),
        Binding("ctrl+c", "terminal_quit", show=False, priority=True),
        Binding("ctrl+d", "terminal_quit", show=False, priority=True),
        Binding("ctrl+backslash", "terminal_quit", show=False, priority=True),
        Binding("b", "go_back", "Back"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "open_selected", "Open"),
        Binding("s", "show_series_key", "Show Key"),
        Binding("c", "clear_series_key", "Clear Key"),
    ]

    LEVEL_DATASETS = "datasets"
    LEVEL_EDITIONS = "editions"
    LEVEL_VERSIONS = "versions"
    LEVEL_DIMENSIONS = "dimensions"
    LEVEL_OPTIONS = "options"

    def __init__(
        self,
        explorer: ONSExplorer,
        *,
        page_size: int,
        max_pages: int,
        preview_limit: int,
        time_series_only: bool,
        skip_time_series_check: bool,
        show_time_dimension: bool,
        contains: Optional[str],
    ) -> None:
        super().__init__()
        self.explorer = explorer
        self.page_size = page_size
        self.max_pages = max_pages
        self.preview_limit = preview_limit
        self.time_series_only = time_series_only
        self.skip_time_series_check = skip_time_series_check
        self.show_time_dimension = show_time_dimension

        self.level = self.LEVEL_DATASETS
        self.current_items: List[Dict[str, Any]] = []
        self.filtered_items: List[Dict[str, Any]] = []

        self.selected_dataset_id: Optional[str] = None
        self.selected_edition: Optional[str] = None
        self.selected_version: Optional[str] = None
        self.selected_dimension: Optional[Dict[str, Any]] = None

        self.series_key: Dict[str, str] = {}
        self.initial_contains = contains or ""
        self.edition_step_skipped = False
        self.fatal_traceback_printed = False
        self.startup_complete = False
        self.loading_active = False
        self.loading_message = ""
        self.loading_started_at = 0.0
        self.loading_frame = 0
        self.loading_logs: List[str] = []
        self.quit_requested_once = False
        self.status_message = ""
        self.rate_limit_until = 0.0
        self.rate_limit_endpoint = ""
        self.last_series_update: Optional[tuple[str, str]] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("Loading ONS Data Explorer...", id="startup_loading")
        with Horizontal(id="breadcrumbs"):
            yield Button("Datasets", id="crumb_datasets", classes="crumb-btn")
            yield Static("/", id="sep_dataset", classes="crumb-sep")
            yield Button("", id="crumb_dataset", classes="crumb-btn")
            yield Static("/", id="sep_edition", classes="crumb-sep")
            yield Button("", id="crumb_edition", classes="crumb-btn")
            yield Static("/", id="sep_version", classes="crumb-sep")
            yield Button("", id="crumb_version", classes="crumb-btn")
            yield Static("/", id="sep_dimension", classes="crumb-sep")
            yield Button("", id="crumb_dimension", classes="crumb-btn")
        yield Input(placeholder="Filter current list... (type to filter)", id="filter")
        with Horizontal(id="main"):
            yield OptionList(id="items")
            yield RichLog(id="detail", wrap=True, highlight=True, markup=False)
        with Horizontal(id="series_bar"):
            yield Static("", id="series_key")
            yield Button("Copy", id="copy_series")
        yield Static("", id="status")
        yield Footer(id="footer")

    def on_mount(self) -> None:
        filter_input = self.query_one("#filter", Input)
        filter_input.value = self.initial_contains
        self._set_main_ui_visible(False)
        self._update_path()
        self._update_series_key_panel()
        self.set_interval(0.15, self._tick_loading)
        self._refresh_current_level()

    def action_go_back(self) -> None:
        if self.level == self.LEVEL_DATASETS:
            self._set_status("Already at top level (datasets).")
            return

        if self.level == self.LEVEL_EDITIONS:
            self.level = self.LEVEL_DATASETS
            self.selected_dataset_id = None
            self.selected_edition = None
            self.selected_version = None
            self.selected_dimension = None
            self.series_key.clear()
            self.edition_step_skipped = False
        elif self.level == self.LEVEL_VERSIONS:
            if self.edition_step_skipped:
                # If editions were auto-skipped, go back to the previous visible page.
                self.level = self.LEVEL_DATASETS
                self.selected_dataset_id = None
                self.selected_edition = None
                self.selected_version = None
                self.selected_dimension = None
                self.series_key.clear()
                self.edition_step_skipped = False
            else:
                self.level = self.LEVEL_EDITIONS
                self.selected_edition = None
                self.selected_version = None
                self.selected_dimension = None
        elif self.level == self.LEVEL_DIMENSIONS:
            self.level = self.LEVEL_VERSIONS
            self.selected_version = None
            self.selected_dimension = None
        elif self.level == self.LEVEL_OPTIONS:
            self.level = self.LEVEL_DIMENSIONS
            self.selected_dimension = None

        self._clear_filter()
        self._update_path()
        self._update_series_key_panel()
        self._refresh_current_level()

    def action_refresh(self) -> None:
        self._refresh_current_level()

    def action_open_selected(self) -> None:
        option_list = self.query_one("#items", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            self._set_status("Nothing is selected.")
            return
        self._open_item_by_index(highlighted)

    def action_show_series_key(self) -> None:
        self._show_series_key_in_detail()

    def action_clear_series_key(self) -> None:
        self.series_key.clear()
        self.last_series_update = None
        self._update_series_key_panel()
        self._set_status("Cleared series_key.")
        self._refresh_current_level()

    def action_block_ctrl_q(self) -> None:
        self._set_status("Ctrl+Q is disabled. Use Ctrl+C to stop the app.")

    def action_terminal_quit(self) -> None:
        if not self.quit_requested_once:
            self.quit_requested_once = True
            self._set_status("Stopping app... press Ctrl+C again to force quit.")
            self.exit(return_code=130)
            return
        self._force_quit_now()

    def on_key(self, event: Key) -> None:
        # Some terminals/widgets consume control keys; catch here as a fallback.
        if event.key in {"ctrl+c", "ctrl+d", "ctrl+backslash"}:
            event.stop()
            self.action_terminal_quit()

    def on_resize(self, event: Resize) -> None:
        del event
        self._update_series_key_panel()

    def _restore_terminal(self) -> None:
        if sys.platform == "win32":
            return
        try:
            if sys.stdin.isatty():
                subprocess.run(
                    ["stty", "sane"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass

    def _force_quit_now(self) -> None:
        self._restore_terminal()
        os._exit(130)

    def _set_main_ui_visible(self, visible: bool) -> None:
        for widget_id in (
            "breadcrumbs",
            "filter",
            "main",
            "series_bar",
            "status",
            "footer",
        ):
            self.query_one(f"#{widget_id}").display = visible
        self.query_one("#startup_loading", Static).display = not visible

    def _finish_startup(self) -> None:
        if self.startup_complete:
            return
        self.startup_complete = True
        self._set_main_ui_visible(True)

    def _handle_exception(self, error: Exception) -> None:
        # Ensure unhandled app exceptions always show in the launching terminal.
        self.fatal_traceback_printed = True
        print(
            "\nONS Data Explorer crashed with an unhandled exception:", file=sys.stderr
        )
        traceback.print_exception(
            type(error), error, error.__traceback__, file=sys.stderr
        )
        super()._handle_exception(error)

    def _clear_filter(self) -> None:
        self.query_one("#filter", Input).value = ""

    def _set_status(self, message: str) -> None:
        if self.loading_active:
            self.loading_message = message
            self._render_loading_or_status()
            return
        self.quit_requested_once = False
        self.status_message = message
        self._render_loading_or_status()

    def _start_loading(self, message: str) -> None:
        self.loading_active = True
        self.loading_message = message
        self.loading_started_at = time.monotonic()
        self.loading_frame = 0
        self.loading_logs.clear()
        self._render_loading_or_status()

    def _stop_loading(self) -> None:
        self.loading_active = False
        self._render_loading_or_status()

    def _log_loading(self, message: str) -> None:
        text = " ".join(str(message).split())
        if not text:
            return
        if self.loading_logs and self.loading_logs[-1] == text:
            return
        self.loading_logs.append(text)
        # Keep the recent activity short and scannable.
        self.loading_logs = self.loading_logs[-6:]
        self._render_loading_or_status()

    def _on_rate_limited(self, endpoint: str, wait_seconds: float) -> None:
        now = time.monotonic()
        self.rate_limit_until = max(self.rate_limit_until, now + max(wait_seconds, 0.1))
        self.rate_limit_endpoint = endpoint
        self._log_loading(
            f"Rate limited on '{endpoint}'. Waiting {wait_seconds:.1f}s before retry."
        )
        self._render_loading_or_status()

    def _rate_limit_suffix(self) -> str:
        if self.rate_limit_until <= 0:
            return ""
        now = time.monotonic()
        remaining = self.rate_limit_until - now
        if remaining <= 0:
            self.rate_limit_until = 0.0
            self.rate_limit_endpoint = ""
            return ""
        endpoint = self.rate_limit_endpoint or "request"
        return f"Rate-Limited ({endpoint}): retry in {remaining:.1f}s"

    def _render_loading_or_status(self) -> None:
        rate_suffix = self._rate_limit_suffix()
        if self.loading_active:
            spinner = "|/-\\"
            glyph = spinner[self.loading_frame % len(spinner)]
            elapsed = time.monotonic() - self.loading_started_at
            base_text = f"{glyph} {self.loading_message} ({elapsed:.1f}s)"
            if rate_suffix:
                base_text = f"{base_text} | {rate_suffix}"
            if self.startup_complete:
                self.query_one("#status", Static).update(base_text)
            else:
                log_text = ""
                if self.loading_logs:
                    lines = "\n".join(f"- {line}" for line in self.loading_logs)
                    log_text = "\n\nRecent Activity:\n" + lines
                self.query_one("#startup_loading", Static).update(
                    "Loading ONS Data Explorer...\n" + base_text + log_text
                )
            self.loading_frame += 1
            return

        text = self.status_message
        if rate_suffix:
            if text:
                text = f"{text} | {rate_suffix}"
            else:
                text = rate_suffix
        if self.startup_complete:
            self.query_one("#status", Static).update(text)
        else:
            self.query_one("#startup_loading", Static).update(
                "Loading ONS Data Explorer...\n" + text
            )

    def _tick_loading(self) -> None:
        self._render_loading_or_status()

    def _set_display(self, widget_id: str, show: bool) -> None:
        self.query_one(f"#{widget_id}").display = show

    def _build_series_snippet(self) -> Optional[str]:
        if not self.selected_dataset_id:
            return None
        display_series_key = self._display_series_key()
        return (
            "MTTimeSeries("
            f"dataset_id='{self.selected_dataset_id}', "
            f"source='ons', series_key={json.dumps(display_series_key, sort_keys=False)}"
            ")"
        )

    def _display_series_key(self) -> Dict[str, str]:
        if not self.series_key:
            return {}
        if self.last_series_update is None:
            return dict(self.series_key)
        dim_id, _ = self.last_series_update
        if dim_id not in self.series_key:
            return dict(self.series_key)
        ordered: Dict[str, str] = {dim_id: self.series_key[dim_id]}
        for key in sorted(self.series_key):
            if key == dim_id:
                continue
            ordered[key] = self.series_key[key]
        return ordered

    def _update_path(self) -> None:
        crumb_datasets = self.query_one("#crumb_datasets", Button)
        crumb_dataset = self.query_one("#crumb_dataset", Button)
        crumb_edition = self.query_one("#crumb_edition", Button)
        crumb_version = self.query_one("#crumb_version", Button)
        crumb_dimension = self.query_one("#crumb_dimension", Button)

        crumb_datasets.label = "Datasets"
        crumb_datasets.disabled = self.level == self.LEVEL_DATASETS

        show_dataset = bool(self.selected_dataset_id)
        show_edition = bool(self.selected_edition)
        show_version = bool(self.selected_version)
        show_dimension = (
            self.level == self.LEVEL_OPTIONS and self.selected_dimension is not None
        )

        if show_dataset:
            crumb_dataset.label = f"Dataset: {self.selected_dataset_id}"
            crumb_dataset.disabled = self.level == self.LEVEL_EDITIONS
        if show_edition:
            crumb_edition.label = f"Edition: {self.selected_edition}"
            crumb_edition.disabled = self.level == self.LEVEL_VERSIONS
        if show_version:
            crumb_version.label = f"Version: {self.selected_version}"
            crumb_version.disabled = self.level == self.LEVEL_DIMENSIONS
        if show_dimension and self.selected_dimension is not None:
            crumb_dimension.label = (
                f"Dimension: {_dimension_key(self.selected_dimension)}"
            )
            crumb_dimension.disabled = self.level == self.LEVEL_OPTIONS

        self._set_display("sep_dataset", show_dataset)
        self._set_display("crumb_dataset", show_dataset)
        self._set_display("sep_edition", show_edition)
        self._set_display("crumb_edition", show_edition)
        self._set_display("sep_version", show_version)
        self._set_display("crumb_version", show_version)
        self._set_display("sep_dimension", show_dimension)
        self._set_display("crumb_dimension", show_dimension)

    def _update_series_key_panel(self) -> None:
        snippet = self._build_series_snippet()
        if snippet is None:
            text = "Constructed Series:\nSelect a dataset and options to construct a series."
        else:
            series_widget = self.query_one("#series_key", Static)
            wrap_width = max(36, (series_widget.size.width or 100) - 2)
            wrapped = textwrap.fill(
                snippet,
                width=wrap_width,
                break_long_words=False,
                break_on_hyphens=False,
            )
            summary = f"Selected Dimensions: {len(self.series_key)}"
            if self.last_series_update is not None:
                summary += (
                    f"\nLast Updated: {self.last_series_update[0]}"
                    f"={self.last_series_update[1]}"
                )
            text = f"{summary}\nConstructed Series:\n{wrapped}"
        self.query_one("#series_key", Static).update(text)

    def _copy_to_clipboard(self, text: str) -> bool:
        commands: List[List[str]] = []
        if sys.platform == "darwin":
            commands = [["pbcopy"]]
        elif sys.platform.startswith("linux"):
            commands = [
                ["wl-copy"],
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"],
            ]
        elif sys.platform == "win32":
            commands = [["clip"]]

        for cmd in commands:
            try:
                subprocess.run(
                    cmd,
                    input=text.encode("utf-8"),
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except Exception:
                continue

        # Fallback to Textual clipboard API when OS clipboard commands are unavailable.
        copy_method = getattr(self, "copy_to_clipboard", None)
        if callable(copy_method):
            try:
                copy_method(text)
                return True
            except Exception:
                pass

        return False

    def action_copy_series(self) -> None:
        snippet = self._build_series_snippet()
        if snippet is None:
            self._set_status("No constructed series to copy yet.")
            return
        if self._copy_to_clipboard(snippet):
            self._set_status("Copied constructed series to clipboard.")
        else:
            self._set_status("Clipboard unavailable in this environment.")

    def _show_series_key_in_detail(self) -> None:
        detail = self.query_one("#detail", RichLog)
        detail.clear()

        snippet = self._build_series_snippet()
        if snippet is None:
            detail.write("Constructed Series")
            detail.write("Select a dataset and options to construct a series.")
            self._set_status("No constructed series yet.")
            return

        detail.write("Constructed Series")
        detail.write(snippet)
        detail.write("")
        detail.write("Selected Series Key")
        detail.write(Pretty(self.series_key, expand_all=True))
        self._set_status("Displayed constructed series in detail pane.")

    def _refresh_current_level(self) -> None:
        self._update_path()
        self._start_loading(f"Loading {self.level}...")
        self._load_level_worker(
            level=self.level,
            dataset_id=self.selected_dataset_id,
            edition=self.selected_edition,
            version=self.selected_version,
            dimension=self.selected_dimension,
        )

    def _order_editions(self, editions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        time_series: List[Dict[str, Any]] = []
        other: List[Dict[str, Any]] = []

        for edition in editions:
            item = dict(edition)
            if item.get("edition") == "time-series":
                item["__edition_group"] = "time-series"
                time_series.append(item)
            else:
                item["__edition_group"] = "other"
                other.append(item)

        if not time_series:
            for item in other:
                item["__no_time_series"] = True

        if self.time_series_only:
            if time_series:
                return time_series
            return []

        return time_series + other

    def _resolve_series_key_support_for_dataset(
        self, dataset_id: str
    ) -> tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """Return whether time-series edition is Macrotrace-compatible.

        Returns:
            (is_supported, block_reason, time_dimension_id, resolved_frequency)
        """
        try:
            version_item = self.explorer.resolve_version(
                dataset_id=dataset_id,
                edition="time-series",
                version_arg="latest",
            )
            version = str(version_item.get("version", ""))
        except Exception as exc:
            return False, f"Unable to validate time-series metadata: {exc}", None, None

        time_dim_id, resolved_freq = _resolve_ons_frequency_from_version_metadata(
            version_item
        )
        if not time_dim_id:
            try:
                version_metadata = self.explorer.get_version_metadata(
                    dataset_id=dataset_id,
                    edition="time-series",
                    version=version,
                )
                time_dim_id, resolved_freq = (
                    _resolve_ons_frequency_from_version_metadata(version_metadata)
                )
            except Exception as exc:
                return (
                    False,
                    f"Unable to validate time-series metadata: {exc}",
                    None,
                    None,
                )
        if not time_dim_id:
            return False, "No time dimension found in time-series metadata.", None, None
        if not resolved_freq:
            return (
                False,
                f"Time dimension type '{time_dim_id}' is not supported.",
                time_dim_id,
                None,
            )

        return True, None, time_dim_id, resolved_freq

    @work(thread=True, exclusive=True)
    def _load_level_worker(
        self,
        *,
        level: str,
        dataset_id: Optional[str],
        edition: Optional[str],
        version: Optional[str],
        dimension: Optional[Dict[str, Any]],
    ) -> None:
        try:
            items: List[Dict[str, Any]]
            if level == self.LEVEL_DATASETS:
                items = self.explorer.list_datasets(
                    page_size=self.page_size,
                    max_pages=self.max_pages,
                )

                if self.skip_time_series_check:
                    items = [
                        dict(dataset) | {"has_time_series": "unknown"}
                        for dataset in items
                    ]
                else:
                    with_ts: List[Dict[str, Any]] = []
                    total = len(items)
                    for idx, dataset in enumerate(items, start=1):
                        ds_id = str(dataset.get("id", ""))
                        self.call_from_thread(
                            self._log_loading,
                            f"Fetching editions for dataset: {ds_id} ({idx}/{total})",
                        )
                        call_started = time.monotonic()
                        editions = self.explorer.list_editions(ds_id) if ds_id else []
                        call_elapsed = time.monotonic() - call_started
                        if call_elapsed >= 2.0:
                            self.call_from_thread(
                                self._log_loading,
                                (
                                    f"Slow response for dataset '{ds_id}': "
                                    f"{call_elapsed:.1f}s"
                                ),
                            )
                        has_ts = any(
                            e.get("edition") == "time-series" for e in editions
                        )
                        if self.time_series_only and not has_ts:
                            continue
                        with_ts.append(dataset | {"has_time_series": has_ts})
                        if total and (idx % 25 == 0 or idx == total):
                            ratio = idx / total
                            bar_width = 18
                            filled = int(ratio * bar_width)
                            bar = "#" * filled + "-" * (bar_width - filled)
                            self.call_from_thread(
                                self._set_status,
                                (
                                    "Checking time-series editions: "
                                    f"{idx}/{total} [{bar}] {ratio * 100:5.1f}%"
                                ),
                            )
                        elif total and idx % 5 == 0:
                            self.call_from_thread(
                                self._set_status,
                                f"Checking time-series editions: {idx}/{total}",
                            )
                    items = with_ts

            elif level == self.LEVEL_EDITIONS:
                if not dataset_id:
                    items = []
                else:
                    items = self._order_editions(
                        self.explorer.list_editions(dataset_id)
                    )
                    ts_items = [
                        item for item in items if item.get("edition") == "time-series"
                    ]
                    if ts_items:
                        (
                            ts_supported,
                            ts_reason,
                            ts_time_dim_id,
                            ts_resolved_freq,
                        ) = self._resolve_series_key_support_for_dataset(dataset_id)
                        for item in ts_items:
                            item["__series_key_supported"] = ts_supported
                            item["__series_key_block_reason"] = ts_reason
                            item["__time_dimension_id"] = ts_time_dim_id
                            item["__resolved_frequency"] = ts_resolved_freq

            elif level == self.LEVEL_VERSIONS:
                if not dataset_id or not edition:
                    items = []
                else:
                    items = self.explorer.list_versions(dataset_id, edition)

            elif level == self.LEVEL_DIMENSIONS:
                if not dataset_id or not edition or not version:
                    items = []
                else:
                    items = self.explorer.list_dimensions(dataset_id, edition, version)
                    if not self.show_time_dimension:
                        items = [item for item in items if not _is_time_dimension(item)]

            elif level == self.LEVEL_OPTIONS:
                if not dataset_id or not edition or not version or dimension is None:
                    items = []
                else:
                    code_list_id = _extract_code_list_id(dimension)
                    if not code_list_id:
                        items = []
                    else:
                        code_list_edition_hint = _extract_code_list_edition(dimension)

                        def _options_progress(page: int, loaded: int) -> None:
                            self.call_from_thread(
                                self._set_status,
                                f"Loading options: page {page}, {loaded} loaded...",
                            )
                            self.call_from_thread(
                                self._log_loading,
                                f"Loaded options page {page}: {loaded} total",
                            )

                        self.call_from_thread(
                            self._set_status,
                            f"Loading options for code list '{code_list_id}'...",
                        )
                        self.call_from_thread(
                            self._log_loading,
                            f"Requesting options for code list '{code_list_id}'",
                        )
                        _, items = self.explorer.list_dimension_options(
                            code_list_id=code_list_id,
                            code_list_edition=code_list_edition_hint,
                            progress_callback=_options_progress,
                        )
            else:
                items = []
        except Exception as exc:
            LOGGER.exception("Failed to load level '%s'.", level)
            self.call_from_thread(self._on_level_load_failed, level, str(exc))
            return

        self.call_from_thread(self._on_level_loaded, level, items)

    def _on_level_load_failed(self, level: str, message: str) -> None:
        if level != self.level:
            return
        self._stop_loading()
        if level == self.LEVEL_DATASETS:
            self._finish_startup()
        self.current_items = []
        self.filtered_items = []
        self._render_option_list()
        self._set_status(f"Failed to load {level}: {message}")

    def _on_level_loaded(self, level: str, items: List[Dict[str, Any]]) -> None:
        if level != self.level:
            return
        self._stop_loading()
        if level == self.LEVEL_DATASETS:
            self._finish_startup()

        self.current_items = items
        self._apply_filter()
        if (
            level == self.LEVEL_DATASETS
            and self.skip_time_series_check
            and self.time_series_only
        ):
            self._set_status(
                f"Loaded {len(items)} datasets. "
                "Skipped time-series filtering because --skip-time-series-check is enabled."
            )
            return

        if level == self.LEVEL_EDITIONS:
            has_time_series = any(i.get("edition") == "time-series" for i in items)
            only_ts = len(items) == 1 and items[0].get("edition") == "time-series"
            if only_ts and items[0].get("__series_key_supported", True):
                self.edition_step_skipped = True
                self.selected_edition = "time-series"
                self.selected_version = None
                self.selected_dimension = None
                self.level = self.LEVEL_VERSIONS
                self._set_status(
                    "Only one selectable edition (time-series). "
                    "Skipping editions page."
                )
                self._clear_filter()
                self._update_path()
                self._refresh_current_level()
                return
            self.edition_step_skipped = False
            if only_ts and not items[0].get("__series_key_supported", True):
                reason = str(
                    items[0].get("__series_key_block_reason")
                    or "Unsupported time dimension type."
                )
                self._set_status(f"Time-series edition is blocked: {reason}")
                return
            if has_time_series:
                if self.time_series_only:
                    blocked_count = sum(
                        1
                        for i in items
                        if i.get("edition") == "time-series"
                        and not i.get("__series_key_supported", True)
                    )
                    self._set_status(
                        f"Loaded {len(items)} edition(s). "
                        "Showing time-series editions only."
                    )
                    if blocked_count:
                        self._set_status(
                            f"Loaded {len(items)} edition(s). {blocked_count} blocked "
                            "for unsupported time dimension type."
                        )
                else:
                    self._set_status(
                        f"Loaded {len(items)} editions. "
                        "Time-series is pinned first; other editions are reference-only."
                    )
            else:
                self._set_status("No time-series edition for this dataset.")
            return

        self._set_status(f"Loaded {len(items)} {level} item(s).")

    def _search_text(self, item: Dict[str, Any]) -> str:
        if self.level == self.LEVEL_DATASETS:
            return f"{item.get('id', '')} {item.get('title', '')} {item.get('description', '')}"
        if self.level == self.LEVEL_EDITIONS:
            return (
                f"{item.get('edition', '')} {item.get('label', '')} "
                f"{item.get('__series_key_block_reason', '')}"
            )
        if self.level == self.LEVEL_VERSIONS:
            return f"{item.get('version', '')} {item.get('release_date', '')}"
        if self.level == self.LEVEL_DIMENSIONS:
            return f"{_dimension_key(item)} {_dimension_label(item)} {_extract_code_list_id(item) or ''}"
        if self.level == self.LEVEL_OPTIONS:
            return f"{item.get('code', '')} {item.get('label', '')}"
        return json.dumps(item)

    def _format_item(self, item: Dict[str, Any]) -> str:
        def compact(value: Any, max_len: int = 180) -> str:
            text = " ".join(str(value or "").split())
            if len(text) <= max_len:
                return text
            return text[: max_len - 1] + "…"

        def block(title: str, lines: List[str]) -> str:
            rendered = [f"[object] {title}"]
            rendered.extend(f"• {line}" for line in lines if line)
            rendered.append("────────────────────")
            return "\n".join(rendered)

        if self.level == self.LEVEL_DATASETS:
            ts = item.get("has_time_series", "n/a")
            description = compact(item.get("description", ""))
            lines = [f"Title: {compact(item.get('title', ''), 120)}"]
            if self.time_series_only:
                if description:
                    lines.append(f"Description: {description}")
            else:
                lines.append(f"Time-Series Edition: {ts}")
                if description:
                    lines.append(f"Description: {description}")
            return block(
                str(item.get("id", "")),
                lines,
            )

        if self.level == self.LEVEL_EDITIONS:
            edition_name = str(item.get("edition", ""))
            latest = item.get("version", "") or (
                item.get("links", {}).get("latest_version", {}).get("id", "")
            )
            is_ts = edition_name == "time-series"
            title = (
                "Time-Series Edition (Macrotrace-compatible)"
                if is_ts
                else f"Other Edition: {edition_name}"
            )
            lines = [
                f"Edition: {edition_name}",
                f"Label: {item.get('label', '')}",
                f"Latest Version: {latest}",
            ]
            if is_ts:
                supported = bool(item.get("__series_key_supported", True))
                if supported:
                    lines.append("Selection: Enabled")
                    if item.get("__resolved_frequency"):
                        lines.append(
                            f"Resolved Frequency: {item.get('__resolved_frequency')}"
                        )
                else:
                    lines.append("Selection: Disabled (Unsupported Time Dimension)")
                    reason = str(
                        item.get("__series_key_block_reason")
                        or "Unsupported time dimension type."
                    )
                    lines.append(f"Block Reason: {reason}")
            else:
                lines.append("Selection: Disabled (Reference-Only)")
            if item.get("__no_time_series"):
                lines.append("Note: this dataset has no time-series edition")
            return block(
                title,
                lines,
            )

        if self.level == self.LEVEL_VERSIONS:
            return block(
                f"Version: {item.get('version', '')}",
                [f"Release Date: {item.get('release_date', '')}"],
            )

        if self.level == self.LEVEL_DIMENSIONS:
            dim_id = _dimension_key(item)
            selected = self.series_key.get(dim_id, "")
            marker = "(x)" if selected else "( )"
            detail_lines = [
                f"Label: {_dimension_label(item)}",
                f"Code List: {_extract_code_list_id(item) or 'n/a'}",
                f"Time Dimension: {_is_time_dimension(item)}",
                f"Status: {'Selected' if selected else 'Not Selected'}",
            ]
            if selected:
                detail_lines.append(f"Selected Option: {selected}")
            return block(f"{marker} {dim_id}", detail_lines)

        if self.level == self.LEVEL_OPTIONS:
            return block(
                str(item.get("code", "")),
                [f"Label: {item.get('label', '')}"],
            )

        return str(item)

    def _apply_filter(self) -> None:
        query = _norm(self.query_one("#filter", Input).value)
        if not query:
            self.filtered_items = list(self.current_items)
        else:
            self.filtered_items = [
                item
                for item in self.current_items
                if query in _norm(self._search_text(item))
            ]

        self._render_option_list()

    def _render_option_list(self) -> None:
        option_list = self.query_one("#items", OptionList)
        option_list.clear_options()

        for item in self.filtered_items:
            option_list.add_option(Option(self._format_item(item)))

        if self.filtered_items:
            option_list.highlighted = 0
            self._update_detail_for_index(0)
        else:
            self._clear_detail()
            self._set_status(f"No results for filter at {self.level}.")

    def _clear_detail(self) -> None:
        self.query_one("#detail", RichLog).clear()

    def _update_detail_for_index(self, index: int) -> None:
        if index < 0 or index >= len(self.filtered_items):
            return

        item = self.filtered_items[index]
        detail = self.query_one("#detail", RichLog)
        detail.clear()
        detail.write(f"Level: {self.level}")

        if self.level == self.LEVEL_EDITIONS:
            has_time_series = any(
                i.get("edition") == "time-series" for i in self.current_items
            )
            other_count = len(
                [i for i in self.current_items if i.get("edition") != "time-series"]
            )
            if item.get("edition") == "time-series":
                supported = bool(item.get("__series_key_supported", True))
                if supported:
                    detail.write(
                        f"Series-key support: enabled (frequency={item.get('__resolved_frequency')})."
                    )
                else:
                    reason = str(
                        item.get("__series_key_block_reason")
                        or "Unsupported time dimension type."
                    )
                    detail.write(f"Series-key support: blocked. {reason}")
            if has_time_series:
                if self.time_series_only:
                    detail.write(
                        "Time-series-only mode: non-time-series editions are hidden."
                    )
                else:
                    detail.write(
                        "Time-series edition is prioritized for navigation. "
                        "Other editions are shown for reference and are not selectable."
                    )
                    detail.write(f"Other editions available: {other_count}")
            else:
                detail.write(
                    "No time-series edition exists for this dataset. "
                    "This dataset cannot be used for Macrotrace series selection."
                )

        if self.level == self.LEVEL_OPTIONS and self.selected_dimension is not None:
            detail.write(
                f"Selecting option for dimension: {_dimension_key(self.selected_dimension)}"
            )

        detail.write(Pretty(item, expand_all=True))

    def _open_item_by_index(self, index: int) -> None:
        if index < 0 or index >= len(self.filtered_items):
            return

        item = self.filtered_items[index]

        if self.level == self.LEVEL_DATASETS:
            new_dataset_id = str(item.get("id", ""))
            if not new_dataset_id:
                self._set_status("Dataset has no id.")
                return

            if new_dataset_id != self.selected_dataset_id:
                self.series_key.clear()

            self.selected_dataset_id = new_dataset_id
            self.selected_edition = None
            self.selected_version = None
            self.selected_dimension = None
            self.edition_step_skipped = False
            self.level = self.LEVEL_EDITIONS

        elif self.level == self.LEVEL_EDITIONS:
            edition = str(item.get("edition", ""))
            if not edition:
                self._set_status("Edition has no name.")
                return
            if edition != "time-series":
                self._set_status(
                    "Only the time-series edition is selectable. "
                    "Other editions are shown for reference."
                )
                return
            if not item.get("__series_key_supported", True):
                reason = str(
                    item.get("__series_key_block_reason")
                    or "Unsupported time dimension type."
                )
                self._set_status(f"Blocked: {reason}")
                return
            self.selected_edition = edition
            self.selected_version = None
            self.selected_dimension = None
            self.edition_step_skipped = False
            self.level = self.LEVEL_VERSIONS

        elif self.level == self.LEVEL_VERSIONS:
            version = str(item.get("version", ""))
            if not version:
                self._set_status("Version item has no version id.")
                return
            self.selected_version = version
            self.selected_dimension = None
            self.level = self.LEVEL_DIMENSIONS

        elif self.level == self.LEVEL_DIMENSIONS:
            code_list_id = _extract_code_list_id(item)
            if not code_list_id:
                self._set_status(
                    f"Dimension '{_dimension_key(item)}' has no code list."
                )
                return
            self.selected_dimension = item
            self.level = self.LEVEL_OPTIONS

        elif self.level == self.LEVEL_OPTIONS:
            if self.selected_dimension is None:
                self._set_status("No active dimension for option selection.")
                return

            if _is_time_dimension(self.selected_dimension):
                self._set_status("Time dimension options are not added to series_key.")
            else:
                dim_id = _dimension_key(self.selected_dimension)
                code = str(item.get("code", ""))
                previous = self.series_key.get(dim_id)
                self.series_key[dim_id] = code
                self.last_series_update = (dim_id, code)
                if previous is None:
                    self._set_status(f"Set series_key[{dim_id}] = {code}")
                elif previous != code:
                    self._set_status(
                        f"Updated series_key[{dim_id}] {previous} -> {code}"
                    )
                else:
                    self._set_status(f"series_key[{dim_id}] unchanged (still {code})")

            self.level = self.LEVEL_DIMENSIONS
            self.selected_dimension = None

        self._clear_filter()
        self._update_path()
        self._update_series_key_panel()
        self._refresh_current_level()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self._apply_filter()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "crumb_datasets":
            self.level = self.LEVEL_DATASETS
            self.selected_dataset_id = None
            self.selected_edition = None
            self.selected_version = None
            self.selected_dimension = None
            self.series_key.clear()
            self.edition_step_skipped = False
            self._clear_filter()
            self._update_path()
            self._update_series_key_panel()
            self._refresh_current_level()
        elif event.button.id == "crumb_dataset":
            if not self.selected_dataset_id:
                return
            self.level = self.LEVEL_EDITIONS
            self.selected_edition = None
            self.selected_version = None
            self.selected_dimension = None
            self.edition_step_skipped = False
            self._clear_filter()
            self._update_path()
            self._update_series_key_panel()
            self._refresh_current_level()
        elif event.button.id == "crumb_edition":
            if not self.selected_dataset_id or not self.selected_edition:
                return
            self.level = self.LEVEL_VERSIONS
            self.selected_version = None
            self.selected_dimension = None
            self._clear_filter()
            self._update_path()
            self._update_series_key_panel()
            self._refresh_current_level()
        elif event.button.id == "crumb_version":
            if (
                not self.selected_dataset_id
                or not self.selected_edition
                or not self.selected_version
            ):
                return
            self.level = self.LEVEL_DIMENSIONS
            self.selected_dimension = None
            self._clear_filter()
            self._update_path()
            self._update_series_key_panel()
            self._refresh_current_level()
        elif event.button.id == "crumb_dimension":
            if (
                not self.selected_dataset_id
                or not self.selected_edition
                or not self.selected_version
                or self.selected_dimension is None
            ):
                return
            self.level = self.LEVEL_OPTIONS
            self._clear_filter()
            self._update_path()
            self._update_series_key_panel()
            self._refresh_current_level()
        elif event.button.id == "copy_series":
            self.action_copy_series()

    def on_option_list_option_highlighted(
        self,
        event: OptionList.OptionHighlighted,
    ) -> None:
        if event.option_list.id != "items":
            return
        if event.option_index is None:
            return
        self._update_detail_for_index(event.option_index)

    def on_option_list_option_selected(
        self,
        event: OptionList.OptionSelected,
    ) -> None:
        if event.option_list.id != "items":
            return
        if event.option_index is None:
            return
        self._open_item_by_index(event.option_index)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Textual ONS explorer (interactive drill-down)."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--cache-name", default=None)
    parser.add_argument(
        "--cache-expiry-seconds",
        type=int,
        default=DEFAULT_CACHE_EXPIRY_SECONDS,
    )
    parser.add_argument("--clear-cache", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument("--contains", default=None)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--preview-limit", type=int, default=25)
    parser.add_argument(
        "--time-series-only",
        dest="time_series_only",
        action="store_true",
        default=True,
        help="Only show datasets that have a time-series edition (default).",
    )
    parser.add_argument(
        "--include-non-time-series",
        dest="time_series_only",
        action="store_false",
        help="Include datasets that do not have a time-series edition.",
    )
    parser.add_argument(
        "--skip-time-series-check",
        action="store_true",
        help="Skip checking each dataset for a time-series edition (faster).",
    )
    parser.add_argument(
        "--show-time-dimension",
        action="store_true",
        help="Include the 'time' dimension in the dimensions list.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    client = ONSExplorerClient(
        base_url=args.base_url,
        use_cache=not args.no_cache,
        cache_name=args.cache_name,
        cache_expiry_seconds=args.cache_expiry_seconds,
        timeout_seconds=args.timeout_seconds,
    )

    if args.clear_cache:
        client.clear_cache()

    app = ONSExplorerTUI(
        ONSExplorer(client),
        page_size=args.page_size,
        max_pages=args.max_pages,
        preview_limit=args.preview_limit,
        time_series_only=args.time_series_only,
        skip_time_series_check=args.skip_time_series_check,
        show_time_dimension=args.show_time_dimension,
        contains=args.contains,
    )

    def _rate_limited(endpoint: str, wait_seconds: float) -> None:
        try:
            app.call_from_thread(app._on_rate_limited, endpoint, wait_seconds)
        except Exception:
            # App may be shutting down; ignore callback delivery issues.
            pass

    client.set_rate_limit_callback(_rate_limited)

    signal_state = {"count": 0}

    def _exit_on_signal(signum: int, _frame: Any) -> None:
        del signum
        signal_state["count"] += 1
        if signal_state["count"] >= 2:
            app._force_quit_now()
        try:
            app.exit(return_code=130)
        finally:
            raise KeyboardInterrupt

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGQUIT):
        try:
            signal.signal(sig, _exit_on_signal)
        except Exception:
            # Some platforms may not support all signals.
            continue

    try:
        app.run()
    except KeyboardInterrupt:
        # Respect normal terminal interrupt semantics.
        return 130
    except Exception as exc:
        print(f"ONS explorer TUI crashed: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1

    finally:
        app._restore_terminal()

    return_code = int(app.return_code or 0)
    if return_code not in (0, 130):
        if not app.fatal_traceback_printed:
            maybe_error = getattr(app, "_exception", None)
            if isinstance(maybe_error, BaseException):
                print(
                    "\nONS Data Explorer exited due to an internal exception:",
                    file=sys.stderr,
                )
                traceback.print_exception(
                    type(maybe_error),
                    maybe_error,
                    maybe_error.__traceback__,
                    file=sys.stderr,
                )
            else:
                print(
                    f"ONS Data Explorer exited with non-zero code {return_code}.",
                    file=sys.stderr,
                )
        return return_code

    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
