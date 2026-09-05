"""World Bank World Development Indicators archive support.

The World Bank Indicators API assigns opaque numeric identifiers to its source
databases. Current World Development Indicators is source ``2``, while WDI
Database Archives is source ``57``. MacroTrace uses ``WDI`` as its canonical
source name and ``WDI_ARCHIVE_SOURCE_ID`` only to address source ``57`` in World
Bank API requests. The number ``57`` is a database identifier, not an edition.

Archive editions have separate ``YYYYMM`` identifiers and are available only to
month precision, not by a verified publication day. MacroTrace therefore stores
WDI release dates as conservative month-end timestamps at midnight UTC and
preserves the original edition identifiers in release provenance.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import quote

import requests
import requests_cache
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
from tqdm import tqdm

from macrotrace._time import ensure_timezone
from macrotrace.models.db import (
    DatasetDimension,
    Observation,
    Release,
    ReleaseDimension,
    SeriesDimensionFilter,
)
from macrotrace.sources.base import (
    APIClient,
    DatasetManager,
    ObservationManager,
    ReleaseManager,
    SeriesManager,
    SourceAdapter,
    UpdateManager,
    UpdateState,
)

logger = logging.getLogger(__name__)

UTC = timezone.utc
WDI_SOURCE = "WDI"
WDI_ARCHIVE_SOURCE_ID = "57"
WDI_SOURCE_NAME = "WDI Database Archives"
WDI_BASE_URL = "https://api.worldbank.org/v2/"
WDI_EDITION_PRECISION = "month"
WDI_VINTAGE_TIMESTAMP_CONVENTION = "month_end_utc"

# Historical and current ISO-like codes used for the same economy in different
# source files. The source code returned by an edition is always retained.
WDI_COUNTRY_ALIASES = {
    "ZAR": "COD",
    "ROM": "ROU",
    "TMP": "TLS",
}


class WDIResponseError(ValueError):
    """Raised when a World Bank archive response has an invalid shape."""


@dataclass(frozen=True)
class WDIEditionResult:
    """Normalized result and request provenance for one WDI archive edition."""

    edition_id: str
    observations: List[Dict[str, Any]]
    request_urls: List[str]
    total_rows: int


def edition_to_vintage_timestamp(edition_id: str) -> datetime:
    """Convert a ``YYYYMM`` edition ID to conservative month-end UTC."""
    if len(edition_id) != 6 or not edition_id.isdigit():
        raise ValueError(f"Invalid WDI edition ID {edition_id!r}. Expected 'YYYYMM'.")
    year = int(edition_id[:4])
    month = int(edition_id[4:])
    if month < 1 or month > 12:
        raise ValueError(
            f"Invalid WDI edition ID {edition_id!r}. Month must be between 01 and 12."
        )
    day = calendar.monthrange(year, month)[1]
    return datetime(year, month, day, tzinfo=UTC)


def country_code_candidates(country: str) -> List[str]:
    """Return a requested World Bank code followed by its explicit alias, if any."""
    requested = country.upper()
    reverse_aliases = {
        current: historical for historical, current in WDI_COUNTRY_ALIASES.items()
    }
    alias = WDI_COUNTRY_ALIASES.get(requested) or reverse_aliases.get(requested)
    return [requested] if alias is None else [requested, alias]


def _retry_after_seconds(exc: BaseException) -> Optional[float]:
    """Return the delay requested by a retryable World Bank response."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    retry_after = response.headers.get("Retry-After")
    if not retry_after:
        return None
    try:
        return max(0.0, float(retry_after))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(retry_after)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max(0.0, (retry_at - datetime.now(tz=UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            logger.warning("Ignoring invalid Retry-After header %r", retry_after)
            return None


_fallback_wait = wait_exponential(max=30)


def wait_retry_after_or_exponential(retry_state) -> float:
    """Use ``Retry-After`` when available, otherwise exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if exc is not None:
        retry_after = _retry_after_seconds(exc)
        if retry_after is not None:
            return retry_after
    return _fallback_wait(retry_state)


def is_retryable_wdi_error(exc: BaseException) -> bool:
    """Return whether a World Bank request failure is transient."""
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if not isinstance(exc, requests.HTTPError) or exc.response is None:
        return False
    status_code = exc.response.status_code
    return status_code == 429 or 500 <= status_code < 600


class WDIAPIClient(APIClient):
    """API client for World Bank source 57 archive data.

    Args:
        indicator: Optional default indicator used by :meth:`edition`.
        country: Optional default country/economy selection used by
            :meth:`edition`.
        cache_settings: Standard MacroTrace request-cache settings.
        cache_path: Standard MacroTrace request-cache path.
        timeout: Per-request connect/read timeout in seconds.
    """

    def __init__(
        self,
        indicator: Optional[str] = None,
        country: str = "all",
        cache_settings: Optional[Dict[str, Any]] = None,
        cache_path: Optional[str] = None,
        timeout: float = 30,
    ):
        super().__init__(
            base_url=WDI_BASE_URL,
            cache_settings=cache_settings,
            cache_path=cache_path,
        )
        self.indicator = indicator
        self.country = country
        self.timeout = timeout
        self._edition_catalogue: Optional[List[Dict[str, Any]]] = None

    def _get_request_headers(self) -> Dict[str, str]:
        """Return public API headers; source 57 requires no authorization."""
        return {}

    def _get_default_params(self) -> Dict[str, str]:
        """Request JSON responses by default."""
        return {"format": "json"}

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_retry_after_or_exponential,
        before_sleep=before_sleep_log(logger, logging.WARNING),
        retry=retry_if_exception(is_retryable_wdi_error),
        reraise=True,
    )
    def _get_response(
        self,
        endpoint: str,
        params: Mapping[str, Any],
        request_kwargs: Dict[str, Any],
    ) -> requests.Response:
        return self._make_response(endpoint, dict(params), **request_kwargs)

    def _request_json(
        self,
        endpoint: str,
        params: Mapping[str, Any],
        *,
        cache_forever: bool,
        force_refresh: bool,
    ) -> tuple[Dict[str, Any], str]:
        request_kwargs: Dict[str, Any] = {"timeout": self.timeout}
        if isinstance(self.session, requests_cache.CachedSession):
            if cache_forever:
                request_kwargs["expire_after"] = -1
            if force_refresh:
                request_kwargs["force_refresh"] = True

        response = self._get_response(endpoint, params, request_kwargs)
        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise WDIResponseError(
                f"World Bank archive returned malformed JSON for {response.url}."
            ) from exc
        if not isinstance(payload, dict):
            raise WDIResponseError(
                f"World Bank archive response for {response.url} must be an object."
            )
        return payload, response.url

    @staticmethod
    def _pagination_value(payload: Mapping[str, Any], key: str, url: str) -> int:
        value = payload.get(key)
        if value is None:
            raise WDIResponseError(
                f"World Bank archive response for {url} has no {key!r}."
            )
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise WDIResponseError(
                f"World Bank archive response for {url} has invalid {key!r}: {value!r}."
            ) from exc
        if parsed < 0 or (key in {"page", "pages", "per_page"} and parsed < 1):
            raise WDIResponseError(
                f"World Bank archive response for {url} has invalid {key!r}: {value!r}."
            )
        return parsed

    def _catalogue_pages(
        self, *, per_page: int, force_refresh: bool
    ) -> tuple[List[Dict[str, Any]], List[str], int]:
        endpoint = f"sources/{WDI_ARCHIVE_SOURCE_ID}/version"
        page = 1
        expected_pages: Optional[int] = None
        expected_total: Optional[int] = None
        editions: List[Dict[str, Any]] = []
        urls: List[str] = []

        while expected_pages is None or page <= expected_pages:
            payload, url = self._request_json(
                endpoint,
                {"per_page": per_page, "page": page},
                cache_forever=False,
                force_refresh=force_refresh,
            )
            urls.append(url)
            response_page = self._pagination_value(payload, "page", url)
            response_pages = self._pagination_value(payload, "pages", url)
            response_total = self._pagination_value(payload, "total", url)
            self._pagination_value(payload, "per_page", url)
            if response_page != page:
                raise WDIResponseError(
                    f"World Bank archive response for {url} reported page "
                    f"{response_page}, expected {page}."
                )
            if expected_pages is None:
                expected_pages = response_pages
                expected_total = response_total
            elif response_pages != expected_pages or response_total != expected_total:
                raise WDIResponseError(
                    "World Bank archive pagination metadata changed while reading "
                    f"{url}."
                )

            source = payload.get("source")
            if not isinstance(source, list):
                raise WDIResponseError(
                    f"World Bank edition catalogue for {url} must contain 'source' as a list."
                )
            archive_sources = [
                item
                for item in source
                if isinstance(item, dict)
                and str(item.get("id")) == WDI_ARCHIVE_SOURCE_ID
            ]
            if len(archive_sources) != 1:
                raise WDIResponseError(
                    f"World Bank edition catalogue for {url} must contain source 57 exactly once."
                )
            concepts = archive_sources[0].get("concept")
            if not isinstance(concepts, list):
                raise WDIResponseError(
                    f"World Bank edition catalogue for {url} has no concept list."
                )
            version_concepts = [
                concept
                for concept in concepts
                if isinstance(concept, dict) and concept.get("id") == "version"
            ]
            if len(version_concepts) != 1 or not isinstance(
                version_concepts[0].get("variable"), list
            ):
                raise WDIResponseError(
                    f"World Bank edition catalogue for {url} has no valid version variables."
                )
            for variable in version_concepts[0]["variable"]:
                if not isinstance(variable, dict):
                    raise WDIResponseError(
                        f"World Bank edition catalogue for {url} contains an invalid version."
                    )
                edition_id = str(variable.get("id", ""))
                vintage_timestamp = edition_to_vintage_timestamp(edition_id)
                editions.append(
                    {
                        "edition_id": edition_id,
                        "edition_label": variable.get("value"),
                        "vintage_timestamp": vintage_timestamp,
                        "edition_precision": WDI_EDITION_PRECISION,
                        "source_id": WDI_ARCHIVE_SOURCE_ID,
                        "source_name": archive_sources[0].get("name", WDI_SOURCE_NAME),
                        "request_url": url,
                    }
                )
            page += 1

        if expected_total is None:
            raise WDIResponseError("World Bank edition catalogue returned no pages.")
        if len(editions) != expected_total:
            raise WDIResponseError(
                "World Bank edition catalogue row count does not match its total: "
                f"received {len(editions)}, expected {expected_total}."
            )
        return editions, urls, expected_total

    def list_editions(
        self, *, per_page: int = 300, force_refresh: bool = False
    ) -> List[Dict[str, Any]]:
        """List all source 57 editions without assuming a fixed count or latest ID."""
        if self._edition_catalogue is None or force_refresh:
            editions, _urls, _total = self._catalogue_pages(
                per_page=per_page, force_refresh=force_refresh
            )
            self._edition_catalogue = sorted(
                editions, key=lambda item: item["edition_id"]
            )
        return [dict(edition) for edition in self._edition_catalogue]

    @staticmethod
    def _variables_by_concept(
        row: Mapping[str, Any], url: str
    ) -> Dict[str, Dict[str, Any]]:
        variables = row.get("variable")
        if not isinstance(variables, list):
            raise WDIResponseError(
                f"World Bank archive data row from {url} has no variable list."
            )
        by_concept: Dict[str, Dict[str, Any]] = {}
        for variable in variables:
            if not isinstance(variable, dict) or not variable.get("concept"):
                raise WDIResponseError(
                    f"World Bank archive data row from {url} has an invalid variable."
                )
            by_concept[str(variable["concept"])] = dict(variable)
        return by_concept

    @staticmethod
    def _required_variable(
        by_concept: Mapping[str, Dict[str, Any]], concept: str, url: str
    ) -> Dict[str, Any]:
        variable = by_concept.get(concept)
        if variable is None:
            raise WDIResponseError(
                f"World Bank archive data row from {url} is missing {concept!r}."
            )
        return variable

    def _normalize_observation(
        self,
        row: Mapping[str, Any],
        *,
        requested_indicator: str,
        requested_edition: str,
        source_name: str,
        request_url: str,
    ) -> Optional[Dict[str, Any]]:
        value = row.get("value")
        if value is None:
            return None
        by_concept = self._variables_by_concept(row, request_url)
        country = self._required_variable(by_concept, "Country", request_url)
        version = self._required_variable(by_concept, "Version", request_url)
        series = self._required_variable(by_concept, "Series", request_url)
        observation_time = self._required_variable(by_concept, "Time", request_url)

        indicator_code = str(series.get("id", ""))
        edition_id = str(version.get("id", ""))
        if indicator_code != requested_indicator:
            raise WDIResponseError(
                f"World Bank archive data from {request_url} returned indicator "
                f"{indicator_code!r}, expected {requested_indicator!r}."
            )
        if edition_id != requested_edition:
            raise WDIResponseError(
                f"World Bank archive data from {request_url} returned edition "
                f"{edition_id!r}, expected {requested_edition!r}."
            )

        time_id = str(observation_time.get("id", ""))
        if (
            len(time_id) != 6
            or not time_id.startswith("YR")
            or not time_id[2:].isdigit()
        ):
            raise WDIResponseError(
                f"World Bank archive data from {request_url} has invalid annual time ID {time_id!r}."
            )
        observation_year = int(time_id[2:])
        try:
            numeric_value = float(value)
        except (TypeError, ValueError) as exc:
            raise WDIResponseError(
                f"World Bank archive data from {request_url} has non-numeric value {value!r}."
            ) from exc

        entity_metadata = dict(country)
        return {
            "indicator_code": indicator_code,
            "indicator_name": series.get("value"),
            "country_code": str(country.get("id", "")),
            "country_name": country.get("value"),
            "entity_type": country.get("type", "unclassified"),
            "entity_metadata": entity_metadata,
            "observation_year": observation_year,
            "observation_date": datetime(observation_year, 1, 1, tzinfo=UTC),
            "edition_id": edition_id,
            "edition_label": version.get("value"),
            "edition_precision": WDI_EDITION_PRECISION,
            "vintage_timestamp": edition_to_vintage_timestamp(edition_id),
            "value": numeric_value,
            "source_id": WDI_ARCHIVE_SOURCE_ID,
            "source_name": source_name,
            "request_url": request_url,
            "variables_by_concept": by_concept,
        }

    def fetch_edition_result(
        self,
        indicator: str,
        edition: str,
        *,
        country: str = "all",
        time_selection: str = "all",
        per_page: int = 40000,
        force_refresh: bool = False,
    ) -> WDIEditionResult:
        """Fetch and normalize every page for one exact archive edition."""
        indicator = indicator.strip()
        country = country.strip()
        time_selection = time_selection.strip()
        edition_to_vintage_timestamp(edition)
        if not indicator or not country or not time_selection:
            raise ValueError(
                "indicator, country, and time_selection must be non-empty."
            )

        endpoint = (
            f"sources/{WDI_ARCHIVE_SOURCE_ID}/country/{quote(country, safe='')}/"
            f"series/{quote(indicator, safe='')}/time/{quote(time_selection, safe='')}/"
            f"version/{edition}/data"
        )
        page = 1
        expected_pages: Optional[int] = None
        expected_total: Optional[int] = None
        raw_rows: List[tuple[Dict[str, Any], str, str]] = []
        urls: List[str] = []

        while expected_pages is None or page <= expected_pages:
            payload, url = self._request_json(
                endpoint,
                {"per_page": per_page, "page": page},
                cache_forever=True,
                force_refresh=force_refresh,
            )
            urls.append(url)
            response_page = self._pagination_value(payload, "page", url)
            response_pages = self._pagination_value(payload, "pages", url)
            response_total = self._pagination_value(payload, "total", url)
            self._pagination_value(payload, "per_page", url)
            if response_page != page:
                raise WDIResponseError(
                    f"World Bank archive response for {url} reported page "
                    f"{response_page}, expected {page}."
                )
            if expected_pages is None:
                expected_pages = response_pages
                expected_total = response_total
            elif response_pages != expected_pages or response_total != expected_total:
                raise WDIResponseError(
                    "World Bank archive pagination metadata changed while reading "
                    f"{url}."
                )

            source = payload.get("source")
            if not isinstance(source, dict):
                raise WDIResponseError(
                    f"World Bank archive data for {url} must contain 'source' as an object."
                )
            if str(source.get("id")) != WDI_ARCHIVE_SOURCE_ID:
                raise WDIResponseError(
                    f"World Bank archive data for {url} returned source "
                    f"{source.get('id')!r}, expected '57'."
                )
            rows = source.get("data")
            if not isinstance(rows, list):
                raise WDIResponseError(
                    f"World Bank archive data for {url} has no data list."
                )
            source_name = str(source.get("name", WDI_SOURCE_NAME))
            for row in rows:
                if not isinstance(row, dict):
                    raise WDIResponseError(
                        f"World Bank archive data for {url} contains a non-object row."
                    )
                raw_rows.append((row, url, source_name))
            page += 1

        if expected_total is None:
            raise WDIResponseError("World Bank archive returned no data pages.")
        if len(raw_rows) != expected_total:
            raise WDIResponseError(
                "World Bank archive data row count does not match its total: "
                f"received {len(raw_rows)}, expected {expected_total}."
            )

        observations: List[Dict[str, Any]] = []
        for row, url, source_name in raw_rows:
            normalized = self._normalize_observation(
                row,
                requested_indicator=indicator,
                requested_edition=edition,
                source_name=source_name,
                request_url=url,
            )
            if normalized is not None:
                observations.append(normalized)
        return WDIEditionResult(
            edition_id=edition,
            observations=observations,
            request_urls=urls,
            total_rows=expected_total,
        )

    def fetch_edition(
        self,
        indicator: str,
        edition: str,
        *,
        country: str = "all",
        time_selection: str = "all",
        per_page: int = 40000,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return normalized non-null observations from one exact edition."""
        return self.fetch_edition_result(
            indicator,
            edition,
            country=country,
            time_selection=time_selection,
            per_page=per_page,
            force_refresh=force_refresh,
        ).observations

    def edition(
        self,
        edition: str,
        *,
        indicator: Optional[str] = None,
        country: Optional[str] = None,
        time_selection: str = "all",
        per_page: int = 40000,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """Retrieve an exact ``YYYYMM`` edition using client defaults if supplied."""
        resolved_indicator = indicator or self.indicator
        if resolved_indicator is None:
            raise ValueError(
                "indicator is required; pass it here or to WDIAPIClient(...)."
            )
        return self.fetch_edition(
            resolved_indicator,
            edition,
            country=country or self.country,
            time_selection=time_selection,
            per_page=per_page,
            force_refresh=force_refresh,
        )


class WDIDatasetManager(DatasetManager):
    """Create WDI indicator and country dimensions in the shared store."""

    def fetch_new_dataset_dimensions(
        self, state: UpdateState
    ) -> List[DatasetDimension]:
        existing = {
            dimension.dataset_dimension_id
            for dimension in self._get_all_local_dataset_dimensions(state.dataset.id)
        }
        missing = {"country", state.dataset_id} - existing
        if not missing:
            return []

        editions = self.api_client.list_editions()
        if not editions:
            raise WDIResponseError("World Bank edition catalogue contains no editions.")
        valid_from = min(item["vintage_timestamp"] for item in editions)
        dimensions = []
        if "country" in missing:
            dimensions.append(
                DatasetDimension(
                    dataset=state.dataset,
                    dataset_dimension_id="country",
                    title="Country or economy",
                    type="text",
                    frequency=None,
                    description=(
                        "World Bank source entity code. Source 57 may include "
                        "aggregates as well as economies."
                    ),
                    units=None,
                    seasonal_adjustment=None,
                    valid_from=valid_from,
                    valid_to=None,
                )
            )
        if state.dataset_id in missing:
            dimensions.append(
                DatasetDimension(
                    dataset=state.dataset,
                    dataset_dimension_id=state.dataset_id,
                    title=state.dataset_id,
                    type="numeric",
                    frequency="YS",
                    description="World Development Indicators archived annual series",
                    units=None,
                    seasonal_adjustment=None,
                    valid_from=valid_from,
                    valid_to=None,
                )
            )
        return dimensions


class WDIReleaseManager(ReleaseManager):
    """Discover month-precision WDI editions and create conservative releases."""

    def fetch_new_releases(self, state: UpdateState) -> List[Release]:
        state.release_start_date = ensure_timezone(state.release_start_date, UTC)
        state.release_end_date = ensure_timezone(state.release_end_date, UTC)
        current_release_dates = self._get_current_releases_in_db(state.dataset.id)
        releases = []
        for edition in self.api_client.list_editions():
            release_date = edition["vintage_timestamp"]
            if self._is_new_release(
                release_date, current_release_dates
            ) and self._is_wanted_release(
                release_date, state.release_start_date, state.release_end_date
            ):
                releases.append(
                    Release(
                        dataset=state.dataset,
                        release_date=release_date,
                        additional_metadata={
                            "source_id": WDI_ARCHIVE_SOURCE_ID,
                            "source_name": edition["source_name"],
                            "edition_id": edition["edition_id"],
                            "edition_label": edition["edition_label"],
                            "edition_precision": WDI_EDITION_PRECISION,
                            "vintage_timestamp_convention": (
                                WDI_VINTAGE_TIMESTAMP_CONVENTION
                            ),
                            "catalogue_url": edition["request_url"],
                            "requests": [],
                        },
                    )
                )
        return releases

    def fetch_new_release_dimensions(
        self, state: UpdateState
    ) -> List[ReleaseDimension]:
        dimensions = self._get_all_local_dataset_dimensions(state.dataset.id)
        return [
            ReleaseDimension(release=release, dimension=dimension)
            for release in state.new_releases or []
            for dimension in dimensions
            if dimension.valid_from <= release.release_date
            and (
                dimension.valid_to is None or dimension.valid_to >= release.release_date
            )
        ]


class WDISeriesManager(SeriesManager):
    """Store the selected World Bank entity as the WDI series dimension."""

    def fetch_new_series_dimension_filters(
        self, state: UpdateState
    ) -> List[SeriesDimensionFilter]:
        existing = self._get_series_dimension_filters(state.series.id)
        country = state.series_key["country"]
        if any(
            item.dataset_dimension_id == "country" and item.value == country
            for item in existing
        ):
            return []
        dimension = DatasetDimension.get(
            (DatasetDimension.dataset == state.dataset)
            & (DatasetDimension.dataset_dimension_id == "country")
        )
        return [
            SeriesDimensionFilter(
                series=state.series,
                dimension=dimension,
                value=country,
            )
        ]


class WDIObservationManager(ObservationManager):
    """Fetch complete WDI snapshots without carrying values across editions."""

    @staticmethod
    def _request_already_recorded(release: Release, country: str) -> bool:
        metadata = release.additional_metadata or {}
        return any(
            request.get("series_key") == {"country": country}
            and request.get("time_selection") == "all"
            for request in metadata.get("requests", [])
            if isinstance(request, dict)
        )

    def _releases_to_fetch(self, state: UpdateState) -> List[Release]:
        conditions = [Release.dataset == state.dataset]
        if state.release_start_date:
            conditions.append(Release.release_date >= state.release_start_date)
        if state.release_end_date:
            conditions.append(Release.release_date <= state.release_end_date)
        releases = Release.select().where(*conditions).order_by(Release.release_date)
        country = state.series_key["country"]
        return [
            release
            for release in releases
            if not self._request_already_recorded(release, country)
        ]

    @staticmethod
    def _record_provenance(
        release: Release,
        *,
        country: str,
        queried_codes: Sequence[str],
        result: WDIEditionResult,
    ) -> None:
        metadata = dict(release.additional_metadata or {})
        requests_metadata = list(metadata.get("requests", []))
        response_entities = {
            observation["country_code"]: {
                "country_code": observation["country_code"],
                "country_name": observation["country_name"],
                "entity_type": observation["entity_type"],
                "entity_metadata": observation["entity_metadata"],
            }
            for observation in result.observations
        }
        requests_metadata.append(
            {
                "series_key": {"country": country},
                "indicator": release.dataset.dataset_id,
                "country_requested": country,
                "country_queried": list(queried_codes),
                "time_selection": "all",
                "request_urls": result.request_urls,
                "response_entities": list(response_entities.values()),
                "source_row_count": result.total_rows,
                "non_null_observation_count": len(result.observations),
            }
        )
        metadata["requests"] = requests_metadata
        release.additional_metadata = metadata
        release.save(only=[Release.additional_metadata])

    def _fetch_with_aliases(
        self, indicator: str, edition_id: str, country: str
    ) -> tuple[WDIEditionResult, List[str]]:
        candidates = country_code_candidates(country)
        combined_urls: List[str] = []
        total_rows = 0
        last_result: Optional[WDIEditionResult] = None
        for position, candidate in enumerate(candidates):
            result = self.api_client.fetch_edition_result(
                indicator,
                edition_id,
                country=candidate,
            )
            combined_urls.extend(result.request_urls)
            total_rows += result.total_rows
            last_result = result
            if result.observations:
                return (
                    WDIEditionResult(
                        edition_id=edition_id,
                        observations=result.observations,
                        request_urls=combined_urls,
                        total_rows=total_rows,
                    ),
                    candidates[: position + 1],
                )
        assert last_result is not None
        return (
            WDIEditionResult(
                edition_id=edition_id,
                observations=[],
                request_urls=combined_urls,
                total_rows=total_rows,
            ),
            candidates,
        )

    def _update_indicator_title(
        self, state: UpdateState, observations: Sequence[Dict[str, Any]]
    ) -> None:
        title = next(
            (
                item.get("indicator_name")
                for item in observations
                if item.get("indicator_name")
            ),
            None,
        )
        if title is None:
            return
        dimension = DatasetDimension.get(
            (DatasetDimension.dataset == state.dataset)
            & (DatasetDimension.dataset_dimension_id == state.dataset_id)
        )
        if dimension.title == state.dataset_id:
            dimension.title = title
            dimension.save(only=[DatasetDimension.title])

    def fetch_new_observations(self, state: UpdateState) -> List[Observation]:
        releases = self._releases_to_fetch(state)
        if not releases:
            return []

        country = state.series_key["country"]
        observations: List[Observation] = []
        for release in tqdm(releases, desc="Processing WDI editions", leave=False):
            metadata = release.additional_metadata or {}
            edition_id = metadata.get("edition_id")
            if not edition_id:
                raise WDIResponseError(
                    f"Stored WDI release {release.release_date} has no edition ID provenance."
                )
            result, queried_codes = self._fetch_with_aliases(
                state.dataset_id, edition_id, country
            )
            self._update_indicator_title(state, result.observations)
            self._record_provenance(
                release,
                country=country,
                queried_codes=queried_codes,
                result=result,
            )
            observations.extend(
                Observation(
                    series=state.series,
                    release=release,
                    observation_timestamp=item["observation_date"],
                    value=item["value"],
                )
                for item in result.observations
            )
        return observations


class WDIUpdateManager(UpdateManager):
    """Ingest one WDI indicator-country series through MacroTrace's normal path."""

    def __init__(
        self,
        dataset_id: str,
        source: str = WDI_SOURCE,
        series_key: Optional[Dict[str, str]] = None,
        release_start_date: Optional[datetime] = None,
        release_end_date: Optional[datetime] = None,
        db_path: Optional[str] = None,
        cache_settings: Optional[Dict[str, Any]] = None,
        cache_path: Optional[str] = None,
    ):
        dataset_id = dataset_id.strip()
        if not dataset_id:
            raise ValueError("WDI indicator code must be non-empty.")
        if series_key is None:
            raise ValueError(
                "WDIUpdateManager requires a normalized country series key. "
                "Use WDI_SOURCE_ADAPTER to construct update managers."
            )
        self.indicator = dataset_id
        self.country = series_key["country"]
        super().__init__(
            dataset_id=dataset_id,
            source=source,
            series_key=series_key,
            release_start_date=release_start_date,
            release_end_date=release_end_date,
            db_path=db_path,
            cache_settings=cache_settings,
            cache_path=cache_path,
        )

    def _create_api_client(
        self,
        cache_settings: Optional[Dict[str, Any]] = None,
        cache_path: Optional[str] = None,
    ) -> WDIAPIClient:
        return WDIAPIClient(
            indicator=self.indicator,
            country=self.country,
            cache_settings=cache_settings,
            cache_path=cache_path,
        )

    def _create_dataset_manager(self) -> DatasetManager:
        return WDIDatasetManager(self.api_client)

    def _create_release_manager(self) -> ReleaseManager:
        return WDIReleaseManager(self.api_client)

    def _create_series_manager(self) -> SeriesManager:
        return WDISeriesManager(self.api_client)

    def _create_observation_manager(self) -> ObservationManager:
        return WDIObservationManager(self.api_client)


class WDISourceAdapter(SourceAdapter):
    """Provide WDI country selection and updater construction."""

    source = WDI_SOURCE
    native_observation_timezone = UTC

    def normalize_series_key(
        self,
        dataset_id: str,
        series_key: Optional[Dict[str, str]],
    ) -> Dict[str, str]:
        if series_key is None:
            raise ValueError(
                "WDI requires one country/economy code, for example "
                "series_key={'country': 'USA'}."
            )
        if not isinstance(series_key, dict):
            raise TypeError(
                "WDI series_key must be a dictionary, for example "
                "{'country': 'USA'}."
            )

        unexpected = set(series_key) - {"country"}
        if unexpected:
            raise ValueError(
                "WDI series_key only supports the 'country' dimension; "
                f"unexpected key(s): {sorted(unexpected)}."
            )
        if "country" not in series_key:
            raise ValueError(
                "WDI requires one country/economy code, for example "
                "series_key={'country': 'USA'}."
            )

        country = series_key["country"]
        if not isinstance(country, str):
            raise TypeError("WDI series_key['country'] must be a string.")

        country = country.strip().upper()
        if not country:
            raise ValueError(
                "WDI requires one country/economy code, for example "
                "series_key={'country': 'USA'}."
            )
        if country == "ALL":
            raise ValueError(
                "MTTimeSeries loads one WDI country/economy at a time. Use "
                "WDIAPIClient.fetch_edition(..., country='all') for panel retrieval."
            )
        return {"country": country}

    def create_update_manager(
        self,
        dataset_id: str,
        series_key: Dict[str, str],
        release_start_date: Optional[datetime] = None,
        release_end_date: Optional[datetime] = None,
        db_path: Optional[str] = None,
        cache_settings: Optional[Dict[str, Any]] = None,
        cache_path: Optional[str] = None,
    ) -> WDIUpdateManager:
        return WDIUpdateManager(
            dataset_id=dataset_id,
            series_key=series_key,
            release_start_date=release_start_date,
            release_end_date=release_end_date,
            db_path=db_path,
            cache_settings=cache_settings,
            cache_path=cache_path,
        )


WDI_SOURCE_ADAPTER = WDISourceAdapter()
