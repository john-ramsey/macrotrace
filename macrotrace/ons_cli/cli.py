"""Interactive ONS API explorer CLI with cached requests."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any, Callable, Dict, List, Optional, TypeVar
from urllib.parse import urlencode

from tabulate import tabulate
from tqdm import tqdm

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

LOGGER = logging.getLogger("ons_explorer")
T = TypeVar("T")


def _parse_kv_pairs(pairs: List[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for item in pairs:
        if "=" not in item:
            raise ValueError(
                f"Invalid --set value '{item}'. Expected format: dimension=code"
            )
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise ValueError(
                f"Invalid --set value '{item}'. Expected non-empty dimension and code."
            )
        parsed[key] = value
    return parsed


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=False))


def _print_table(rows: List[List[Any]], headers: List[str]) -> None:
    if not rows:
        print("No results.")
        return
    print(tabulate(rows, headers=headers, tablefmt="github"))


def _interactive_select_item(
    *,
    title: str,
    items: List[T],
    headers: List[str],
    row_builder: Callable[[T], List[Any]],
    search_text_builder: Callable[[T], str],
    page_size: int,
    allow_back: bool = True,
    empty_message: str = "No results.",
) -> Optional[T]:
    if not items:
        print(empty_message)
        return None

    query = ""
    page = 0
    page_size = max(page_size, 1)

    while True:
        if query:
            needle = _norm(query)
            filtered = [
                item for item in items if needle in _norm(search_text_builder(item))
            ]
        else:
            filtered = items

        total = len(filtered)
        max_page = max((total - 1) // page_size, 0) if total else 0
        if page > max_page:
            page = max_page

        start = page * page_size
        end = min(start + page_size, total)
        page_items = filtered[start:end]

        query_msg = f" | filter='{query}'" if query else ""
        print(f"\n{title} ({total} item(s), page {page + 1}/{max_page + 1}{query_msg})")
        if page_items:
            rows = [
                [idx + 1] + row_builder(item) for idx, item in enumerate(page_items)
            ]
            _print_table(rows, ["#"] + headers)
        else:
            print(
                "No items on this page. Use '/text' to change filter or '/' to clear it."
            )

        commands = ["<number>=open", "/text=filter", "/=clear filter"]
        if total > page_size:
            commands.extend(["n=next page", "p=previous page"])
        if allow_back:
            commands.append("b=back")
        commands.append("q=quit")
        print("Commands: " + ", ".join(commands))

        try:
            raw = input("Select: ").strip()
        except EOFError:
            raise KeyboardInterrupt("User exited browse mode.")

        normalized = _norm(raw)
        if normalized in {"q", "quit", "exit"}:
            raise KeyboardInterrupt("User exited browse mode.")
        if allow_back and normalized in {"b", "back"}:
            return None
        if normalized in {"n", "next"}:
            if page < max_page:
                page += 1
            else:
                print("Already on the last page.")
            continue
        if normalized in {"p", "prev", "previous"}:
            if page > 0:
                page -= 1
            else:
                print("Already on the first page.")
            continue
        if raw.startswith("/"):
            query = raw[1:].strip()
            page = 0
            continue
        if normalized.isdigit():
            index = int(normalized) - 1
            if 0 <= index < len(page_items):
                return page_items[index]
            print("Invalid selection number for this page.")
            continue

        print("Invalid command.")


def _apply_contains_filter(
    rows: List[Dict[str, Any]],
    *,
    contains: Optional[str],
    fields: List[str],
) -> List[Dict[str, Any]]:
    if not contains:
        return rows

    needle = _norm(contains)
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        for field in fields:
            text = str(row.get(field, ""))
            if needle in _norm(text):
                filtered.append(row)
                break
    return filtered


def _slice_for_display(
    rows: List[Dict[str, Any]], show_all: bool, limit: int
) -> List[Dict[str, Any]]:
    if show_all:
        return rows
    return rows[: max(0, limit)]


def _series_key_query_string(series_key: Dict[str, str]) -> str:
    return urlencode(series_key)


def _interactive_pick_code(
    *,
    dimension_id: str,
    dimension_label: str,
    options: List[Dict[str, Any]],
    preview_limit: int,
) -> str:
    options_by_code: Dict[str, str] = {
        str(item.get("code")): str(item.get("label", ""))
        for item in options
        if item.get("code") is not None
    }

    if not options_by_code:
        raise ValueError(
            f"No options available for dimension '{dimension_id}' ({dimension_label})."
        )

    option_rows = [[code, label] for code, label in sorted(options_by_code.items())]
    print(f"\nDimension: {dimension_id} ({dimension_label})")
    print(
        "Enter an option code. Use '/text' to filter by code/label, "
        "'list' to show the first options, and 'quit' to abort."
    )
    _print_table(option_rows[:preview_limit], ["code", "label"])

    while True:
        raw = input(f"Select code for {dimension_id}: ").strip()
        if not raw:
            continue
        if _norm(raw) in {"quit", "exit", "q"}:
            raise KeyboardInterrupt("User aborted series-key generation.")
        if _norm(raw) == "list":
            _print_table(option_rows[:preview_limit], ["code", "label"])
            continue
        if raw.startswith("/"):
            term = _norm(raw[1:])
            matches = [
                [code, label]
                for code, label in sorted(options_by_code.items())
                if term in _norm(code) or term in _norm(label)
            ]
            _print_table(matches[:preview_limit], ["code", "label"])
            if len(matches) > preview_limit:
                print(
                    f"Showing first {preview_limit} of {len(matches)} match(es). "
                    "Refine with a narrower /filter or enter the exact code."
                )
            continue
        if raw in options_by_code:
            print(f"Selected {dimension_id}={raw} ({options_by_code[raw]})")
            return raw

        print(
            f"'{raw}' is not a valid code for '{dimension_id}'. "
            "Use 'list' or '/text' to inspect options."
        )


def cmd_datasets(explorer: ONSExplorer, args: argparse.Namespace) -> None:
    datasets = explorer.list_datasets(
        page_size=args.page_size, max_pages=args.max_pages
    )
    datasets = _apply_contains_filter(
        datasets,
        contains=args.contains,
        fields=["id", "title", "description"],
    )

    if args.skip_time_series_check and args.time_series_only:
        raise ValueError("Cannot use --time-series-only with --skip-time-series-check.")

    if not args.skip_time_series_check:
        annotated: List[Dict[str, Any]] = []
        for dataset in tqdm(datasets, desc="Checking for time-series editions"):
            editions = explorer.list_editions(dataset["id"])
            has_time_series = any(e.get("edition") == "time-series" for e in editions)
            if args.time_series_only and not has_time_series:
                continue
            annotated.append(dataset | {"has_time_series": has_time_series})
        datasets = annotated

    datasets = _slice_for_display(datasets, show_all=args.show_all, limit=args.limit)

    if args.json:
        _print_json(datasets)
        return

    rows = [
        [
            item.get("id", ""),
            item.get("title", ""),
            item.get("has_time_series", "n/a"),
            item.get("links", {}).get("self", {}).get("href", ""),
        ]
        for item in datasets
    ]
    _print_table(rows, ["dataset_id", "title", "has_time_series", "self_link"])


def cmd_editions(explorer: ONSExplorer, args: argparse.Namespace) -> None:
    editions = explorer.list_editions(args.dataset_id)

    if args.json:
        _print_json(editions)
        return

    rows = [
        [
            item.get("edition", ""),
            item.get("label", ""),
            item.get("version", "")
            or item.get("links", {}).get("latest_version", {}).get("id", ""),
        ]
        for item in editions
    ]
    _print_table(rows, ["edition", "label", "latest_version"])


def cmd_versions(explorer: ONSExplorer, args: argparse.Namespace) -> None:
    versions = explorer.list_versions(dataset_id=args.dataset_id, edition=args.edition)

    if args.json:
        _print_json(versions)
        return

    rows = [
        [
            item.get("version", ""),
            item.get("release_date", ""),
            item.get("id", ""),
        ]
        for item in versions
    ]
    _print_table(rows, ["version", "release_date", "id"])


def cmd_dimensions(explorer: ONSExplorer, args: argparse.Namespace) -> None:
    version_item = explorer.resolve_version(
        dataset_id=args.dataset_id,
        edition=args.edition,
        version_arg=args.version,
    )
    version = str(version_item["version"])
    dimensions = explorer.list_dimensions(
        dataset_id=args.dataset_id,
        edition=args.edition,
        version=version,
    )

    if args.json:
        _print_json({"version": version_item, "dimensions": dimensions})
        return

    rows = []
    for dim in dimensions:
        rows.append(
            [
                _dimension_key(dim),
                _dimension_label(dim),
                _extract_code_list_id(dim) or "",
                _is_time_dimension(dim),
            ]
        )

    print(f"Resolved version: {version}")
    _print_table(rows, ["dimension", "label", "code_list_id", "is_time"])


def cmd_options(explorer: ONSExplorer, args: argparse.Namespace) -> None:
    version_item = explorer.resolve_version(
        dataset_id=args.dataset_id,
        edition=args.edition,
        version_arg=args.version,
    )
    version = str(version_item["version"])

    dimensions = explorer.list_dimensions(
        dataset_id=args.dataset_id,
        edition=args.edition,
        version=version,
    )
    dim = explorer.resolve_dimension(dimensions, args.dimension)

    code_list_id = _extract_code_list_id(dim)
    if not code_list_id:
        raise ValueError(
            f"Dimension '{_dimension_key(dim)}' has no code list; cannot list options."
        )

    requested_edition = args.code_list_edition or _extract_code_list_edition(dim)
    code_list_edition, options = explorer.list_dimension_options(
        code_list_id=code_list_id,
        code_list_edition=requested_edition,
    )

    options = _apply_contains_filter(
        options, contains=args.contains, fields=["code", "label"]
    )
    options = _slice_for_display(options, show_all=args.show_all, limit=args.limit)

    if args.json:
        _print_json(
            {
                "dataset_id": args.dataset_id,
                "edition": args.edition,
                "version": version,
                "dimension": _dimension_key(dim),
                "code_list_id": code_list_id,
                "code_list_edition": code_list_edition,
                "options": options,
            }
        )
        return

    print(f"Resolved dataset version: {version}")
    print(f"Dimension: {_dimension_key(dim)} ({_dimension_label(dim)})")
    print(f"Code list: {code_list_id} (edition: {code_list_edition})")

    rows = [[item.get("code", ""), item.get("label", "")] for item in options]
    _print_table(rows, ["code", "label"])


def cmd_series_key(explorer: ONSExplorer, args: argparse.Namespace) -> None:
    if _norm(args.edition) != "time-series":
        raise ValueError(
            "series-key only supports the 'time-series' edition for Macrotrace compatibility."
        )

    preselected = _parse_kv_pairs(args.set or [])
    preselected_norm = {_norm(k): v for k, v in preselected.items()}

    version_item = explorer.resolve_version(
        dataset_id=args.dataset_id,
        edition=args.edition,
        version_arg=args.version,
    )
    version = str(version_item["version"])

    dimensions = explorer.list_dimensions(
        dataset_id=args.dataset_id,
        edition=args.edition,
        version=version,
    )
    time_dim_id, resolved_freq = _resolve_ons_frequency_from_version_metadata(
        version_item
    )
    if not time_dim_id:
        version_metadata = explorer.get_version_metadata(
            dataset_id=args.dataset_id,
            edition=args.edition,
            version=version,
        )
        time_dim_id, resolved_freq = _resolve_ons_frequency_from_version_metadata(
            version_metadata
        )
    if not time_dim_id:
        raise ValueError(
            f"Dataset '{args.dataset_id}' version '{version}' has no time dimension."
        )
    if not resolved_freq:
        raise ValueError(
            f"Dataset '{args.dataset_id}' version '{version}' has unsupported time "
            f"dimension id '{time_dim_id}' (ONS_TO_PD_FREQUENCIES maps to null)."
        )

    target_dims = [dim for dim in dimensions if not _is_time_dimension(dim)]
    if not target_dims:
        print("No non-time dimensions were found. series_key = {}")
        return

    series_key: Dict[str, str] = {}
    for dim in target_dims:
        dimension_id = _dimension_key(dim)
        normalized_id = _norm(dimension_id)
        label = _dimension_label(dim)

        provided_value = preselected_norm.get(normalized_id)

        code_list_id = _extract_code_list_id(dim)
        if not code_list_id:
            raise ValueError(
                f"Dimension '{dimension_id}' has no code list and cannot be used to build a series key."
            )

        code_list_edition_hint = _extract_code_list_edition(dim)
        code_list_edition, options = explorer.list_dimension_options(
            code_list_id=code_list_id,
            code_list_edition=code_list_edition_hint,
        )
        valid_codes = {str(item.get("code")) for item in options}

        if provided_value:
            if provided_value not in valid_codes:
                raise ValueError(
                    f"Invalid code '{provided_value}' for dimension '{dimension_id}' "
                    f"(code-list: {code_list_id}, edition: {code_list_edition})."
                )
            series_key[dimension_id] = provided_value
            continue

        if args.non_interactive:
            raise ValueError(
                f"Missing --set for required dimension '{dimension_id}'. "
                "Use --set dimension=code or run without --non-interactive."
            )

        selected = _interactive_pick_code(
            dimension_id=dimension_id,
            dimension_label=label,
            options=options,
            preview_limit=args.preview_limit,
        )
        series_key[dimension_id] = selected

    payload = {
        "dataset_id": args.dataset_id,
        "edition": args.edition,
        "version": version,
        "time_dimension_id": time_dim_id,
        "resolved_frequency": resolved_freq,
        "series_key": series_key,
        "query_string": _series_key_query_string(series_key),
    }

    if args.json:
        _print_json(payload)
        return

    print("\nSeries key generated:")
    _print_json(series_key)
    print("\nQuery string:")
    print(payload["query_string"])
    print("\nMacrotrace snippet:")
    print(
        "MTTimeSeries("
        f"dataset_id='{args.dataset_id}', source='ons', series_key={json.dumps(series_key)}"
        ")"
    )


def cmd_inspect(explorer: ONSExplorer, args: argparse.Namespace) -> None:
    dataset = explorer.get_dataset(args.dataset_id)
    editions = explorer.list_editions(args.dataset_id)

    payload: Dict[str, Any] = {
        "dataset": {
            "id": dataset.get("id"),
            "title": dataset.get("title"),
            "description": dataset.get("description"),
            "unit_of_measure": dataset.get("unit_of_measure"),
            "links": dataset.get("links", {}),
        },
        "editions": editions,
    }

    selected_edition = args.edition
    edition_names = {e.get("edition") for e in editions}
    if selected_edition in edition_names:
        versions = explorer.list_versions(args.dataset_id, selected_edition)
        payload["versions"] = versions
        if versions:
            version_item = explorer.resolve_version(
                dataset_id=args.dataset_id,
                edition=selected_edition,
                version_arg=args.version,
            )
            version = str(version_item["version"])
            payload["resolved_version"] = version_item
            payload["dimensions"] = explorer.list_dimensions(
                dataset_id=args.dataset_id,
                edition=selected_edition,
                version=version,
            )

    if args.json:
        _print_json(payload)
        return

    print(f"Dataset: {dataset.get('id')}\nTitle: {dataset.get('title', '')}")
    if dataset.get("description"):
        print(f"Description: {dataset.get('description')}")

    edition_rows = [[e.get("edition", ""), e.get("label", "")] for e in editions]
    print("\nEditions:")
    _print_table(edition_rows, ["edition", "label"])

    if "versions" not in payload:
        print(f"\nEdition '{selected_edition}' was not found for this dataset.")
        return

    version_rows = [
        [v.get("version", ""), v.get("release_date", "")]
        for v in payload.get("versions", [])
    ]
    print(f"\nVersions for edition '{selected_edition}':")
    _print_table(version_rows, ["version", "release_date"])

    dims = payload.get("dimensions", [])
    if dims:
        dim_rows = [
            [
                _dimension_key(d),
                _dimension_label(d),
                _extract_code_list_id(d) or "",
                _is_time_dimension(d),
            ]
            for d in dims
        ]
        print("\nDimensions for resolved version:")
        _print_table(dim_rows, ["dimension", "label", "code_list_id", "is_time"])


def _print_series_key_result(
    dataset_id: str,
    edition: str,
    version: str,
    series_key: Dict[str, str],
) -> None:
    payload = {
        "dataset_id": dataset_id,
        "edition": edition,
        "version": version,
        "series_key": series_key,
        "query_string": _series_key_query_string(series_key),
    }
    print("\nSeries key generated:")
    _print_json(payload["series_key"])
    print("\nQuery string:")
    print(payload["query_string"])
    print("\nMacrotrace snippet:")
    print(
        "MTTimeSeries("
        f"dataset_id='{dataset_id}', source='ons', series_key={json.dumps(series_key)}"
        ")"
    )


def _browse_dimensions_and_options(
    explorer: ONSExplorer,
    *,
    dataset_id: str,
    edition: str,
    version: str,
    preview_limit: int,
) -> None:
    if _norm(edition) != "time-series":
        print("Series key building is only supported for the 'time-series' edition.")
        return

    version_item = explorer.resolve_version(
        dataset_id=dataset_id,
        edition=edition,
        version_arg=version,
    )
    time_dim_id, resolved_freq = _resolve_ons_frequency_from_version_metadata(
        version_item
    )
    if not time_dim_id:
        version_metadata = explorer.get_version_metadata(
            dataset_id=dataset_id,
            edition=edition,
            version=version,
        )
        time_dim_id, resolved_freq = _resolve_ons_frequency_from_version_metadata(
            version_metadata
        )
    if not time_dim_id:
        print(
            f"Dataset '{dataset_id}' version '{version}' has no time dimension; "
            "series key building is unavailable."
        )
        return
    if not resolved_freq:
        print(
            f"Dataset '{dataset_id}' version '{version}' has unsupported time "
            f"dimension id '{time_dim_id}' (ONS_TO_PD_FREQUENCIES maps to null)."
        )
        return

    dimensions = explorer.list_dimensions(
        dataset_id=dataset_id,
        edition=edition,
        version=version,
    )
    if not dimensions:
        print("No dimensions found for this version.")
        return

    series_key: Dict[str, str] = {}
    while True:
        print("\n" f"Dataset={dataset_id} | Edition={edition} | Version={version}")
        rows = []
        for idx, dim in enumerate(dimensions):
            dim_id = _dimension_key(dim)
            rows.append(
                [
                    idx + 1,
                    dim_id,
                    _dimension_label(dim),
                    _extract_code_list_id(dim) or "",
                    _is_time_dimension(dim),
                    series_key.get(dim_id, ""),
                ]
            )
        _print_table(
            rows,
            ["#", "dimension", "label", "code_list_id", "is_time", "series_key_value"],
        )
        if series_key:
            print("Current series_key:")
            _print_json(series_key)

        print(
            "Commands: <number>=open dimension options, d=done, c=clear series key, b=back, q=quit"
        )
        raw = input("Dimension: ").strip()
        normalized = _norm(raw)
        if normalized in {"q", "quit", "exit"}:
            raise KeyboardInterrupt("User exited browse mode.")
        if normalized in {"b", "back"}:
            return
        if normalized in {"c", "clear"}:
            series_key.clear()
            continue
        if normalized in {"d", "done"}:
            if not series_key:
                print("No non-time dimension selections yet.")
            else:
                _print_series_key_result(dataset_id, edition, version, series_key)
            return

        if not normalized.isdigit():
            print("Invalid command.")
            continue

        dim_index = int(normalized) - 1
        if not (0 <= dim_index < len(dimensions)):
            print("Invalid dimension number.")
            continue

        dim = dimensions[dim_index]
        dim_id = _dimension_key(dim)
        code_list_id = _extract_code_list_id(dim)
        if not code_list_id:
            print(f"Dimension '{dim_id}' does not expose a code list.")
            continue

        code_list_edition_hint = _extract_code_list_edition(dim)
        code_list_edition, options = explorer.list_dimension_options(
            code_list_id=code_list_id,
            code_list_edition=code_list_edition_hint,
        )

        selected_option = _interactive_select_item(
            title=(
                f"Options for {dim_id} "
                f"(code-list {code_list_id}, edition {code_list_edition})"
            ),
            items=options,
            headers=["code", "label"],
            row_builder=lambda item: [
                str(item.get("code", "")),
                str(item.get("label", "")),
            ],
            search_text_builder=lambda item: (
                f"{item.get('code', '')} {item.get('label', '')}"
            ),
            page_size=preview_limit,
            allow_back=True,
            empty_message=f"No options found for dimension '{dim_id}'.",
        )
        if selected_option is None:
            continue

        selected_code = str(selected_option.get("code"))
        selected_label = str(selected_option.get("label", ""))
        print(f"Selected option: {selected_code} ({selected_label})")

        if _is_time_dimension(dim):
            print(
                "Time dimension options are exploratory only and are not added to series_key."
            )
        else:
            series_key[dim_id] = selected_code
            print(f"Set series_key[{dim_id}] = {selected_code}")


def cmd_browse(explorer: ONSExplorer, args: argparse.Namespace) -> None:
    datasets = explorer.list_datasets(
        page_size=args.page_size,
        max_pages=args.max_pages,
    )
    datasets = _apply_contains_filter(
        datasets,
        contains=args.contains,
        fields=["id", "title", "description"],
    )

    if args.skip_time_series_check and args.time_series_only:
        raise ValueError("Cannot use --time-series-only with --skip-time-series-check.")

    if not args.skip_time_series_check:
        annotated: List[Dict[str, Any]] = []
        for dataset in tqdm(datasets, desc="Checking for time-series editions"):
            editions = explorer.list_editions(dataset["id"])
            has_time_series = any(e.get("edition") == "time-series" for e in editions)
            if args.time_series_only and not has_time_series:
                continue
            annotated.append(dataset | {"has_time_series": has_time_series})
        datasets = annotated

    if not datasets:
        print("No datasets available after applying filters.")
        return

    while True:
        dataset = _interactive_select_item(
            title="Datasets",
            items=datasets,
            headers=["dataset_id", "title", "has_time_series"],
            row_builder=lambda item: [
                str(item.get("id", "")),
                str(item.get("title", "")),
                str(item.get("has_time_series", "n/a")),
            ],
            search_text_builder=lambda item: (
                f"{item.get('id', '')} {item.get('title', '')} {item.get('description', '')}"
            ),
            page_size=args.preview_limit,
            allow_back=False,
            empty_message="No datasets available.",
        )
        if dataset is None:
            return

        dataset_id = str(dataset.get("id", ""))
        if not dataset_id:
            print("Selected dataset has no id; choose another.")
            continue
        print(f"\nSelected dataset: {dataset_id} ({dataset.get('title', '')})")

        try:
            latest_ts_version_item = explorer.resolve_version(
                dataset_id=dataset_id,
                edition="time-series",
                version_arg="latest",
            )
            latest_ts_version = str(latest_ts_version_item.get("version", ""))
            time_dim_id, resolved_freq = _resolve_ons_frequency_from_version_metadata(
                latest_ts_version_item
            )
            if not time_dim_id:
                latest_ts_version_metadata = explorer.get_version_metadata(
                    dataset_id=dataset_id,
                    edition="time-series",
                    version=latest_ts_version,
                )
                time_dim_id, resolved_freq = (
                    _resolve_ons_frequency_from_version_metadata(
                        latest_ts_version_metadata
                    )
                )
            if not time_dim_id:
                print(
                    f"Dataset '{dataset_id}' has no time dimension in latest "
                    "time-series version; choose another dataset."
                )
                continue
            if not resolved_freq:
                print(
                    f"Dataset '{dataset_id}' has unsupported latest time-series "
                    f"frequency id '{time_dim_id}' "
                    "(ONS_TO_PD_FREQUENCIES maps to null); choose another dataset."
                )
                continue
        except Exception as exc:
            print(
                f"Dataset '{dataset_id}' is not eligible for series key building: {exc}"
            )
            continue

        while True:
            editions = [
                edition_item
                for edition_item in explorer.list_editions(dataset_id)
                if _norm(str(edition_item.get("edition", ""))) == "time-series"
            ]
            edition = _interactive_select_item(
                title=f"Editions for {dataset_id}",
                items=editions,
                headers=["edition", "label", "latest_version"],
                row_builder=lambda item: [
                    str(item.get("edition", "")),
                    str(item.get("label", "")),
                    str(
                        item.get("version", "")
                        or item.get("links", {}).get("latest_version", {}).get("id", "")
                    ),
                ],
                search_text_builder=lambda item: (
                    f"{item.get('edition', '')} {item.get('label', '')}"
                ),
                page_size=args.preview_limit,
                allow_back=True,
                empty_message=f"No editions found for dataset '{dataset_id}'.",
            )
            if edition is None:
                break

            edition_name = str(edition.get("edition", ""))
            if not edition_name:
                print("Selected edition has no name; choose another.")
                continue
            print(f"\nSelected edition: {edition_name}")

            while True:
                versions = explorer.list_versions(dataset_id, edition_name)
                version_item = _interactive_select_item(
                    title=f"Versions for {dataset_id}/{edition_name}",
                    items=versions,
                    headers=["version", "release_date", "id"],
                    row_builder=lambda item: [
                        str(item.get("version", "")),
                        str(item.get("release_date", "")),
                        str(item.get("id", "")),
                    ],
                    search_text_builder=lambda item: (
                        f"{item.get('version', '')} {item.get('release_date', '')} {item.get('id', '')}"
                    ),
                    page_size=args.preview_limit,
                    allow_back=True,
                    empty_message=(
                        f"No versions found for dataset '{dataset_id}' and edition '{edition_name}'."
                    ),
                )
                if version_item is None:
                    break

                version = str(version_item.get("version", ""))
                if not version:
                    print("Selected version has no version id; choose another.")
                    continue
                print(f"\nSelected version: {version}")

                _browse_dimensions_and_options(
                    explorer,
                    dataset_id=dataset_id,
                    edition=edition_name,
                    version=version,
                    preview_limit=args.preview_limit,
                )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Explore ONS datasets/editions/versions/dimensions and build series keys.",
    )

    parser.add_argument(
        "--base-url", default=DEFAULT_BASE_URL, help="ONS API base URL."
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable HTTP response caching for this run.",
    )
    parser.add_argument(
        "--cache-name",
        default=None,
        help=(
            "requests-cache SQLite basename/path. Defaults to the shared "
            "macrotrace request cache (MACROTRACE_CACHE env var, or "
            "MacroTraceRequestCache.sqlite next to the database). "
            "Example: --cache-name /tmp/ons_cache"
        ),
    )
    parser.add_argument(
        "--cache-expiry-seconds",
        type=int,
        default=DEFAULT_CACHE_EXPIRY_SECONDS,
        help="Cache TTL in seconds (default: 604800 / 7 days).",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear cache before running command.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=60,
        help="HTTP timeout in seconds (default: 60).",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: WARNING).",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    browse = subparsers.add_parser(
        "browse",
        help=(
            "Interactive explorer: dataset -> edition -> version -> dimensions -> options"
        ),
    )
    browse.add_argument(
        "--contains",
        default=None,
        help="Initial dataset filter (id/title/description).",
    )
    browse.add_argument(
        "--skip-time-series-check",
        action="store_true",
        help="Skip checking each dataset for a time-series edition (faster).",
    )
    browse.add_argument(
        "--time-series-only",
        action="store_true",
        help="Only show datasets that have a time-series edition.",
    )
    browse.add_argument(
        "--page-size",
        type=int,
        default=1000,
        help="API pagination page size for initial dataset listing (default: 1000).",
    )
    browse.add_argument(
        "--max-pages",
        type=int,
        default=50,
        help="Max pagination pages for initial dataset listing (default: 50).",
    )
    browse.add_argument(
        "--preview-limit",
        type=int,
        default=20,
        help="Rows shown per interactive page (default: 20).",
    )

    datasets = subparsers.add_parser(
        "datasets",
        help="List ONS datasets and optionally whether they have a time-series edition.",
    )
    datasets.add_argument(
        "--contains", default=None, help="Filter by dataset id/title text."
    )
    datasets.add_argument(
        "--skip-time-series-check",
        action="store_true",
        help="Skip checking each dataset for a time-series edition (faster).",
    )
    datasets.add_argument(
        "--time-series-only",
        action="store_true",
        help="Only show datasets that have a time-series edition.",
    )
    datasets.add_argument(
        "--page-size",
        type=int,
        default=1000,
        help="API pagination page size for dataset listing (default: 1000).",
    )
    datasets.add_argument(
        "--max-pages",
        type=int,
        default=50,
        help="Max pagination pages for dataset listing (default: 50).",
    )
    datasets.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Max rows to print unless --show-all is set (default: 100).",
    )
    datasets.add_argument(
        "--show-all",
        action="store_true",
        help="Show all rows.",
    )
    datasets.add_argument("--json", action="store_true", help="Emit JSON output.")

    editions = subparsers.add_parser("editions", help="List editions for a dataset.")
    editions.add_argument("dataset_id")
    editions.add_argument("--json", action="store_true", help="Emit JSON output.")

    versions = subparsers.add_parser(
        "versions", help="List versions for a dataset edition (default: time-series)."
    )
    versions.add_argument("dataset_id")
    versions.add_argument("--edition", default="time-series")
    versions.add_argument("--json", action="store_true", help="Emit JSON output.")

    dimensions = subparsers.add_parser(
        "dimensions",
        help="List dimensions for a dataset edition/version.",
    )
    dimensions.add_argument("dataset_id")
    dimensions.add_argument("--edition", default="time-series")
    dimensions.add_argument(
        "--version",
        default="latest",
        help="Version number or 'latest' (default: latest).",
    )
    dimensions.add_argument("--json", action="store_true", help="Emit JSON output.")

    options = subparsers.add_parser(
        "options",
        help="List options for a dimension's code list.",
    )
    options.add_argument("dataset_id")
    options.add_argument("dimension", help="Dimension name/id/label.")
    options.add_argument("--edition", default="time-series")
    options.add_argument("--version", default="latest")
    options.add_argument(
        "--code-list-edition",
        default=None,
        help="Override code-list edition.",
    )
    options.add_argument("--contains", default=None, help="Filter by code/label text.")
    options.add_argument("--limit", type=int, default=100)
    options.add_argument("--show-all", action="store_true")
    options.add_argument("--json", action="store_true", help="Emit JSON output.")

    series_key = subparsers.add_parser(
        "series-key",
        help="Interactively build and validate a series key.",
    )
    series_key.add_argument("dataset_id")
    series_key.add_argument("--edition", default="time-series")
    series_key.add_argument("--version", default="latest")
    series_key.add_argument(
        "--set",
        action="append",
        default=[],
        help="Preselect dimension option using dimension=code. Can be repeated.",
    )
    series_key.add_argument(
        "--non-interactive",
        action="store_true",
        help="Require --set for all non-time dimensions.",
    )
    series_key.add_argument(
        "--preview-limit",
        type=int,
        default=20,
        help="Max options shown at once in interactive mode (default: 20).",
    )
    series_key.add_argument("--json", action="store_true", help="Emit JSON output.")

    inspect = subparsers.add_parser(
        "inspect",
        help="Show dataset metadata, editions, versions, and dimensions in one command.",
    )
    inspect.add_argument("dataset_id")
    inspect.add_argument("--edition", default="time-series")
    inspect.add_argument("--version", default="latest")
    inspect.add_argument("--json", action="store_true", help="Emit JSON output.")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

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

    explorer = ONSExplorer(client)

    command_map = {
        "browse": cmd_browse,
        "datasets": cmd_datasets,
        "editions": cmd_editions,
        "versions": cmd_versions,
        "dimensions": cmd_dimensions,
        "options": cmd_options,
        "series-key": cmd_series_key,
        "inspect": cmd_inspect,
    }

    try:
        command_map[args.command](explorer, args)
        return 0
    except KeyboardInterrupt as exc:
        print(str(exc), file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
