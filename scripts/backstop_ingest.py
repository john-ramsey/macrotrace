"""
Backstop ingest harness for external-source redundancy checks.

This is intentionally NOT a pytest test. It runs ingest the same way a user does:
through MTTimeSeries(...), which triggers update_prior_to_load=True by default.

Run:
    uv run python scripts/backstop_ingest.py
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from dotenv import load_dotenv
from dateutil import parser as date_parser

from macrotrace import MTTimeSeries

LOGGER = logging.getLogger("backstop_ingest")

FRED_SOURCES: Dict[str, Dict[str, str]] = {
    "Gross Domestic Product": {"dataset_id": "GDP"},
    "Consumer Price Index for All Urban Consumers: All Items in U.S. City Average": {
        "dataset_id": "CPIAUCSL"
    },
    "Treasury Yield: 48 Month CD <100M": {"dataset_id": "TY48MCD"},
    "Unemployment Rate": {"dataset_id": "UNRATE"},
    "Export Price Index (End Use): Nonmonetary Gold": {"dataset_id": "IQ12260"},
    "All Employees, Total Nonfarm": {"dataset_id": "PAYEMS"},
    "Producer Price Index by Commodity: All Commodities": {"dataset_id": "PPIACO"},
    "30-Year Fixed Rate Mortgage Average in the United States": {
        "dataset_id": "MORTGAGE30US"
    },
    "Federal Funds Effective Rate ": {"dataset_id": "FEDFUNDS"},
    "M2": {"dataset_id": "WM2NS"},
}

ONS_SOURCES: Dict[str, Dict[str, object]] = {
    "uk_monthly_gdp_total": {
        "dataset_id": "gdp-to-four-decimal-places",
        "series_key": {
            "geography": "K02000001",
            "unofficialstandardindustrialclassification": "A--T",
        },
    },
    "'london_working_population_estimates": {
        "dataset_id": "ageing-population-estimates",
        "series_key": {
            "unitofmeasure": "number",
            "agegroups": "16-spa",
            "geography": "E12000007",
            "sex": "all",
        },
    },
    "london_home_sales_september": {
        "dataset_id": "house-prices-local-authority",
        "series_key": {
            "propertytype": "all",
            "buildstatus": "all",
            "geography": "E09000001",
            "housesalesandprices": "sales",
            "month": "sep",
        },
    },
    "sandwell_new_build_median_price_dec": {
        "dataset_id": "house-prices-local-authority",
        "series_key": {
            "propertytype": "all",
            "buildstatus": "newly-built",
            "geography": "E08000028",
            "housesalesandprices": "median",
            "month": "dec",
        },
    },
    "online_job_adverts_week_1": {
        "dataset_id": "online-job-advert-estimates",
        "series_key": {
            "week": "week-1",
            "adzunajobscategory": "all-industries",
            "geography": "K02000001",
        },
    },
    "london_jan_bus_activity": {
        "dataset_id": "traffic-camera-activity",
        "series_key": {
            "trafficcameraarea": "london",
            "daymonth": "01-01",
            "geography": "K02000001",
            "pedestriansandvehicles": "buses",
            "seasonaladjustment": "non-seasonal-adjustment",
        },
    },
}


@dataclass
class IngestResult:
    source: str
    source_name: str
    dataset_id: str
    status: str
    duration_seconds: float
    vintages_available: int
    latest_observation_count: int
    latest_release_date: Optional[str]
    series_key: Optional[Dict[str, str]] = None
    error: Optional[str] = None


def _parse_date_to_utc(date_value: str) -> datetime:
    dt = date_parser.isoparse(date_value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_placeholder_value(value: object) -> bool:
    if isinstance(value, str):
        return value.startswith("__REPLACE_")
    if isinstance(value, dict):
        return any(
            _is_placeholder_value(k) or _is_placeholder_value(v)
            for k, v in value.items()
        )
    return False


def _ingest_one(
    *,
    source: str,
    source_name: str,
    dataset_id: str,
    vintage_start_date: datetime,
    series_key: Optional[Dict[str, str]] = None,
) -> IngestResult:
    start = time.perf_counter()
    try:
        ts = MTTimeSeries(
            dataset_id=dataset_id,
            source=source,
            series_key=series_key,
            vintage_start_date=vintage_start_date,
        )
        duration = time.perf_counter() - start
        vintages_available = len(ts.vintages) + 1
        latest_release_date = (
            ts.release_date.isoformat()
            if isinstance(ts.release_date, datetime)
            else None
        )
        return IngestResult(
            source=source.upper(),
            source_name=source_name,
            dataset_id=dataset_id,
            status="success",
            duration_seconds=duration,
            vintages_available=vintages_available,
            latest_observation_count=len(ts.current_observations),
            latest_release_date=latest_release_date,
            series_key=series_key,
        )
    except Exception as exc:
        duration = time.perf_counter() - start
        return IngestResult(
            source=source.upper(),
            source_name=source_name,
            dataset_id=dataset_id,
            status="failure",
            duration_seconds=duration,
            vintages_available=0,
            latest_observation_count=0,
            latest_release_date=None,
            series_key=series_key,
            error=str(exc),
        )


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run external ingest backstop (10 FRED + 10 ONS) via MTTimeSeries."
    )
    parser.add_argument(
        "--vintage-start-date",
        default="2019-01-01",
        help="ISO-8601 release start date to limit ingest volume (default: 2019-01-01).",
    )
    parser.add_argument(
        "--max-failures",
        type=int,
        default=0,
        help="Return non-zero only if failures exceed this value (default: 0).",
    )
    parser.add_argument(
        "--summary-json",
        default=None,
        help="Optional path to write run summary JSON.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    return parser


def main() -> int:
    load_dotenv()
    args = _build_cli().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not os.getenv("FRED_API_KEY"):
        LOGGER.error("FRED_API_KEY is not set; FRED ingestion cannot run.")
        return 2

    vintage_start_date = _parse_date_to_utc(args.vintage_start_date)
    results: List[IngestResult] = []

    LOGGER.info("Starting FRED ingest (%d sources)", len(FRED_SOURCES))
    for source_name, config in FRED_SOURCES.items():
        dataset_id = str(config["dataset_id"])
        LOGGER.info("FRED start: %s (%s)", source_name, dataset_id)
        result = _ingest_one(
            source="fred",
            source_name=source_name,
            dataset_id=dataset_id,
            vintage_start_date=vintage_start_date,
        )
        results.append(result)
        LOGGER.info(
            "FRED %s: %s (vintages=%d, latest_obs=%d, %.2fs)",
            result.status,
            source_name,
            result.vintages_available,
            result.latest_observation_count,
            result.duration_seconds,
        )

    LOGGER.info("Starting ONS ingest (%d sources)", len(ONS_SOURCES))
    for source_name, config in ONS_SOURCES.items():
        dataset_id = str(config["dataset_id"])
        series_key = config.get("series_key")
        if not isinstance(series_key, dict):
            raise ValueError(
                f"ONS source '{source_name}' must define a dict series_key."
            )

        if _is_placeholder_value(dataset_id) or _is_placeholder_value(series_key):
            result = IngestResult(
                source="ONS",
                source_name=source_name,
                dataset_id=dataset_id,
                status="skipped",
                duration_seconds=0.0,
                vintages_available=0,
                latest_observation_count=0,
                latest_release_date=None,
                series_key=series_key,  # type: ignore[arg-type]
                error="Placeholder config not replaced.",
            )
            results.append(result)
            LOGGER.warning("ONS skipped: %s uses placeholder values", source_name)
            continue

        LOGGER.info("ONS start: %s (%s)", source_name, dataset_id)
        result = _ingest_one(
            source="ons",
            source_name=source_name,
            dataset_id=dataset_id,
            series_key=series_key,  # type: ignore[arg-type]
            vintage_start_date=vintage_start_date,
        )
        results.append(result)
        LOGGER.info(
            "ONS %s: %s (vintages=%d, latest_obs=%d, %.2fs)",
            result.status,
            source_name,
            result.vintages_available,
            result.latest_observation_count,
            result.duration_seconds,
        )

    failures = [r for r in results if r.status == "failure"]
    skipped = [r for r in results if r.status == "skipped"]
    successes = [r for r in results if r.status == "success"]

    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "vintage_start_date": args.vintage_start_date,
        "total": len(results),
        "successes": len(successes),
        "failures": len(failures),
        "skipped": len(skipped),
        "max_failures": args.max_failures,
        "results": [asdict(result) for result in results],
    }

    print(json.dumps(summary, indent=2))

    if args.summary_json:
        path = Path(args.summary_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        LOGGER.info("Summary written to %s", path)

    if len(failures) > args.max_failures:
        LOGGER.error(
            "Failure threshold exceeded: %d failures (max allowed: %d)",
            len(failures),
            args.max_failures,
        )
        return 1

    LOGGER.info(
        "Backstop complete: %d success, %d failure, %d skipped",
        len(successes),
        len(failures),
        len(skipped),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
