"""Shared ONS explorer core for both CLI and TUI."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests
import requests_cache
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Keep ONS explorer frequency compatibility aligned with the core ONS source logic.
from macrotrace.sources.ons import ONS_TO_PD_FREQUENCIES

from macrotrace._paths import resolve_cache_path

DEFAULT_BASE_URL = "https://api.beta.ons.gov.uk/v1/"
DEFAULT_CACHE_EXPIRY_SECONDS = 7 * 24 * 60 * 60
LOGGER = logging.getLogger("ons_explorer")


class ONSExplorerClient:
    """Thin ONS API client with optional requests-cache backing."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        use_cache: bool = True,
        cache_name: Optional[str] = None,
        cache_expiry_seconds: int = DEFAULT_CACHE_EXPIRY_SECONDS,
        timeout_seconds: int = 60,
        rate_limit_callback: Optional[Callable[[str, float], None]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self.rate_limit_callback = rate_limit_callback

        if use_cache:
            self.session = requests_cache.CachedSession(
                cache_name=resolve_cache_path(cache_name),
                expire_after=cache_expiry_seconds,
            )
        else:
            self.session = requests.Session()

    def set_rate_limit_callback(
        self,
        callback: Optional[Callable[[str, float], None]],
    ) -> None:
        self.rate_limit_callback = callback

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type(
            (requests.exceptions.RequestException, requests.exceptions.HTTPError)
        ),
        before_sleep=before_sleep_log(LOGGER, logging.WARNING),
        reraise=True,
    )
    def make_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params = params or {}
        url = self.base_url + endpoint.lstrip("/")

        for _ in range(4):
            response = self.session.get(
                url, params=params, timeout=self.timeout_seconds
            )
            if response.status_code != 429:
                break

            retry_after = response.headers.get("Retry-After", "2")
            try:
                wait_seconds = max(float(retry_after), 0.5)
            except ValueError:
                wait_seconds = 2.0

            LOGGER.warning(
                "Rate limited for %s; waiting %.1f second(s) before retry.",
                endpoint,
                wait_seconds,
            )
            callback = self.rate_limit_callback
            if callback is not None:
                try:
                    callback(endpoint, wait_seconds)
                except Exception:
                    LOGGER.exception("Rate-limit callback failed for %s", endpoint)
            time.sleep(wait_seconds)

        response.raise_for_status()
        return response.json()

    def make_paginated_request(
        self,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        items_key: str = "items",
        limit_param: str = "limit",
        offset_param: str = "offset",
        page_size: int = 1000,
        max_pages: int = 50,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[Dict[str, Any]]:
        params = params or {}
        all_items: List[Dict[str, Any]] = []

        for page_idx in range(max_pages):
            page_params = dict(params)
            page_params[limit_param] = page_size
            page_params[offset_param] = page_idx * page_size
            payload = self.make_request(endpoint=endpoint, params=page_params)

            if isinstance(payload, list):
                items = payload
            else:
                items = payload.get(items_key, [])

            if not isinstance(items, list):
                raise ValueError(
                    f"Expected list in response for endpoint '{endpoint}', got {type(items).__name__}."
                )

            all_items.extend(items)
            if progress_callback is not None:
                progress_callback(page_idx + 1, len(all_items))
            if len(items) < page_size:
                return all_items

        raise RuntimeError(
            f"Pagination limit reached for endpoint '{endpoint}'. Increase --max-pages if needed."
        )

    def clear_cache(self) -> None:
        cache = getattr(self.session, "cache", None)
        if cache is not None:
            cache.clear()


class ONSExplorer:
    def __init__(self, client: ONSExplorerClient):
        self.client = client

    def list_datasets(self, *, page_size: int, max_pages: int) -> List[Dict[str, Any]]:
        datasets = self.client.make_paginated_request(
            "datasets",
            items_key="items",
            page_size=page_size,
            max_pages=max_pages,
        )
        return sorted(
            datasets,
            key=lambda item: (
                str(item.get("id") or "").casefold(),
                str(item.get("title") or "").casefold(),
            ),
        )

    def get_dataset(self, dataset_id: str) -> Dict[str, Any]:
        return self.client.make_request(f"datasets/{dataset_id}")

    def list_editions(self, dataset_id: str) -> List[Dict[str, Any]]:
        payload = self.client.make_request(f"datasets/{dataset_id}/editions")
        return payload.get("items", [])

    def list_versions(self, dataset_id: str, edition: str) -> List[Dict[str, Any]]:
        versions = self.client.make_paginated_request(
            f"datasets/{dataset_id}/editions/{edition}/versions",
            items_key="items",
            page_size=1000,
            max_pages=50,
        )
        return sorted(versions, key=version_sort_key, reverse=True)

    def resolve_version(
        self,
        dataset_id: str,
        edition: str,
        version_arg: str,
    ) -> Dict[str, Any]:
        versions = self.list_versions(dataset_id=dataset_id, edition=edition)
        if not versions:
            raise ValueError(
                f"No versions found for dataset '{dataset_id}' and edition '{edition}'."
            )

        if version_arg == "latest":
            return versions[0]

        for version in versions:
            if str(version.get("version")) == str(version_arg):
                return version

        known_versions = ", ".join(str(v.get("version")) for v in versions[:10])
        raise ValueError(
            f"Version '{version_arg}' not found for dataset '{dataset_id}' (edition '{edition}'). "
            f"Known versions include: {known_versions}"
        )

    def get_version_metadata(
        self,
        dataset_id: str,
        edition: str,
        version: str,
    ) -> Dict[str, Any]:
        return self.client.make_request(
            f"datasets/{dataset_id}/editions/{edition}/versions/{version}"
        )

    def list_dimensions(
        self, dataset_id: str, edition: str, version: str
    ) -> List[Dict[str, Any]]:
        payload = self.client.make_request(
            f"datasets/{dataset_id}/editions/{edition}/versions/{version}/dimensions",
            params={"limit": 1000},
        )
        return payload.get("items", [])

    def resolve_dimension(
        self,
        dimensions: Iterable[Dict[str, Any]],
        dimension_query: str,
    ) -> Dict[str, Any]:
        norm_query = norm_text(dimension_query)
        for dim in dimensions:
            if norm_query in {
                norm_text(dimension_key(dim)),
                norm_text(str(dim.get("id", ""))),
                norm_text(str(dim.get("label", ""))),
                norm_text(str(dim.get("name", ""))),
            }:
                return dim

        available = ", ".join(sorted(dimension_key(d) for d in dimensions))
        raise ValueError(
            f"Dimension '{dimension_query}' not found. Available dimensions: {available}"
        )

    def list_code_list_editions(self, code_list_id: str) -> List[Dict[str, Any]]:
        payload = self.client.make_request(
            f"code-lists/{code_list_id}/editions",
            params={"limit": 1000},
        )
        return payload.get("items", [])

    def list_dimension_options(
        self,
        *,
        code_list_id: str,
        code_list_edition: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> tuple[str, List[Dict[str, Any]]]:
        if not code_list_edition:
            editions = self.list_code_list_editions(code_list_id)
            if not editions:
                raise ValueError(f"No code-list editions found for '{code_list_id}'.")
            code_list_edition = pick_latest_code_list_edition(editions)

        codes = self.client.make_paginated_request(
            f"code-lists/{code_list_id}/editions/{code_list_edition}/codes",
            items_key="items",
            page_size=1000,
            max_pages=100,
            progress_callback=progress_callback,
        )
        return code_list_edition, sorted(
            codes, key=lambda item: str(item.get("code", ""))
        )


def parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        return datetime.min.replace(tzinfo=timezone.utc)
    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def coerce_int(value: Any, fallback: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def version_sort_key(version_item: Dict[str, Any]) -> tuple[datetime, int]:
    return parse_datetime(version_item.get("release_date")), coerce_int(
        version_item.get("version")
    )


def norm_text(value: str) -> str:
    return value.strip().casefold()


def dimension_key(dimension: Dict[str, Any]) -> str:
    for key in ("name", "id", "label"):
        value = dimension.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return "unknown_dimension"


def dimension_label(dimension: Dict[str, Any]) -> str:
    return str(dimension.get("label") or dimension_key(dimension))


def is_time_dimension(dimension: Dict[str, Any]) -> bool:
    key = norm_text(dimension_key(dimension))
    label = norm_text(dimension_label(dimension))
    return key == "time" or label == "time"


def resolve_ons_frequency_from_dimensions(
    dimensions: Iterable[Dict[str, Any]],
) -> tuple[Optional[str], Optional[str]]:
    """Resolve ONS time-dimension id and mapped pandas frequency.

    Returns:
        tuple[Optional[str], Optional[str]]:
            (time_dimension_id, pandas_frequency). If no time dimension is present,
            returns (None, None). If present but unsupported, returns
            (time_dimension_id, None).
    """
    time_dim = next(
        (
            dim
            for dim in dimensions
            if norm_text(str(dim.get("name", ""))) == "time" or is_time_dimension(dim)
        ),
        None,
    )
    if time_dim is None:
        return None, None

    time_dimension_id = str(time_dim.get("id", "")).strip() or None
    if not time_dimension_id:
        return None, None

    return time_dimension_id, ONS_TO_PD_FREQUENCIES.get(time_dimension_id)


def resolve_ons_frequency_from_version_metadata(
    version_metadata: Dict[str, Any],
) -> tuple[Optional[str], Optional[str]]:
    """Resolve ONS frequency from version metadata dimensions.

    This mirrors `macrotrace.sources.ons.ONSDataSetManager._get_freq_from_dim_metadata`,
    which uses the time dimension contained in the version metadata payload
    (`/datasets/{id}/editions/{edition}/versions/{version}`).
    """
    dimensions = version_metadata.get("dimensions", [])
    if not isinstance(dimensions, list):
        return None, None

    time_dim = next(
        (
            dim
            for dim in dimensions
            if isinstance(dim, dict) and norm_text(str(dim.get("name", ""))) == "time"
        ),
        None,
    )
    if time_dim is None:
        return None, None

    time_dimension_id = str(time_dim.get("id", "")).strip() or None
    if not time_dimension_id:
        return None, None

    return time_dimension_id, ONS_TO_PD_FREQUENCIES.get(time_dimension_id)


def extract_code_list_id(dimension: Dict[str, Any]) -> Optional[str]:
    code_list = dimension.get("links", {}).get("code_list", {})
    code_list_id = code_list.get("id")
    if isinstance(code_list_id, str) and code_list_id:
        return code_list_id

    href = code_list.get("href")
    if isinstance(href, str):
        match = re.search(r"/code-lists/([^/]+)", href)
        if match:
            return match.group(1)

    return None


def extract_code_list_edition(dimension: Dict[str, Any]) -> Optional[str]:
    code_list = dimension.get("links", {}).get("code_list", {})
    edition = code_list.get("edition")
    if isinstance(edition, str) and edition:
        return edition

    href = code_list.get("href")
    if isinstance(href, str):
        match = re.search(r"/editions/([^/]+)", href)
        if match:
            return match.group(1)

    return None


def pick_latest_code_list_edition(editions: List[Dict[str, Any]]) -> str:
    if not editions:
        raise ValueError("Cannot pick latest code-list edition from an empty list.")

    def sort_key(item: Dict[str, Any]) -> tuple[datetime, int, str]:
        edition = str(item.get("edition", ""))
        return (
            parse_datetime(item.get("last_updated")),
            coerce_int(edition),
            edition,
        )

    return sorted(editions, key=sort_key, reverse=True)[0]["edition"]
