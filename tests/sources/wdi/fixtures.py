from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pytest

from macrotrace.sources.wdi import WDIAPIClient, WDIEditionResult

UTC = timezone.utc
INDICATOR = "NY.GDP.PCAP.KD"


def edition_record(edition_id: str, label: str) -> Dict[str, Any]:
    month_end = {
        "201406": datetime(2014, 6, 30, tzinfo=UTC),
        "201407": datetime(2014, 7, 31, tzinfo=UTC),
    }[edition_id]
    return {
        "edition_id": edition_id,
        "edition_label": label,
        "vintage_timestamp": month_end,
        "edition_precision": "month",
        "source_id": "57",
        "source_name": "WDI Database Archives",
        "request_url": "https://api.worldbank.org/v2/sources/57/version?page=1",
    }


def normalized_observation(
    edition_id: str,
    year: int,
    value: float,
    *,
    country_code: str = "USA",
    country_name: str = "United States",
) -> Dict[str, Any]:
    return {
        "indicator_code": INDICATOR,
        "indicator_name": "GDP per capita (constant 2010 US$)",
        "country_code": country_code,
        "country_name": country_name,
        "entity_type": "unclassified",
        "entity_metadata": {
            "concept": "Country",
            "id": country_code,
            "value": country_name,
        },
        "observation_year": year,
        "observation_date": datetime(year, 1, 1, tzinfo=UTC),
        "edition_id": edition_id,
        "edition_label": "2014 Jun" if edition_id == "201406" else "2014 Jul",
        "edition_precision": "month",
        "vintage_timestamp": (
            datetime(2014, 6, 30, tzinfo=UTC)
            if edition_id == "201406"
            else datetime(2014, 7, 31, tzinfo=UTC)
        ),
        "value": value,
        "source_id": "57",
        "source_name": "WDI Database Archives",
        "request_url": f"https://api.worldbank.org/example/{country_code}/{edition_id}",
        "variables_by_concept": {},
    }


@pytest.fixture
def api_client():
    return WDIAPIClient(cache_settings={"caching": False})


@pytest.fixture
def catalogue_pages():
    return [
        (
            {
                "page": 1,
                "pages": 2,
                "per_page": 1,
                "total": 2,
                "source": [
                    {
                        "id": "57",
                        "name": "WDI Database Archives",
                        "concept": [
                            {
                                "id": "version",
                                "variable": [{"id": "201406", "value": "2014 Jun"}],
                            }
                        ],
                    }
                ],
            },
            "https://api.worldbank.org/catalogue?page=1",
        ),
        (
            {
                "page": 2,
                "pages": 2,
                "per_page": 1,
                "total": 2,
                "source": [
                    {
                        "id": "57",
                        "name": "WDI Database Archives",
                        "concept": [
                            {
                                "id": "version",
                                "variable": [{"id": "201407", "value": "2014 Jul"}],
                            }
                        ],
                    }
                ],
            },
            "https://api.worldbank.org/catalogue?page=2",
        ),
    ]


def data_row(
    year: int,
    value: Optional[float],
    *,
    country_code: str = "USA",
    country_name: str = "United States",
) -> Dict[str, Any]:
    # Deliberately shuffled: production parsing must index by concept.
    return {
        "variable": [
            {"concept": "Time", "id": f"YR{year}", "value": str(year)},
            {
                "concept": "Series",
                "id": INDICATOR,
                "value": "GDP per capita (constant 2010 US$)",
            },
            {"concept": "Country", "id": country_code, "value": country_name},
            {"concept": "Version", "id": "201407", "value": "2014 Jul"},
        ],
        "value": value,
    }


@pytest.fixture
def data_pages():
    return [
        (
            {
                "page": 1,
                "pages": 2,
                "per_page": 2,
                "total": 3,
                "source": {
                    "id": "57",
                    "name": "WDI Database Archives",
                    "data": [data_row(2011, 100.5), data_row(2012, None)],
                },
            },
            "https://api.worldbank.org/data?page=1",
        ),
        (
            {
                "page": 2,
                "pages": 2,
                "per_page": 2,
                "total": 3,
                "source": {
                    "id": "57",
                    "name": "WDI Database Archives",
                    "data": [data_row(2013, 110.25)],
                },
            },
            "https://api.worldbank.org/data?page=2",
        ),
    ]


@pytest.fixture
def edition_results():
    return {
        "201406": WDIEditionResult(
            edition_id="201406",
            observations=[
                normalized_observation("201406", 2011, 10.0),
                normalized_observation("201406", 2012, 20.0),
            ],
            request_urls=["https://api.worldbank.org/example/USA/201406"],
            total_rows=2,
        ),
        "201407": WDIEditionResult(
            edition_id="201407",
            observations=[
                normalized_observation("201407", 2011, 11.0),
                normalized_observation("201407", 2013, 30.0),
            ],
            request_urls=["https://api.worldbank.org/example/USA/201407"],
            total_rows=2,
        ),
    }
