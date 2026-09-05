# World Development Indicators Archives (WDI)

## Overview

The World Bank's **World Development Indicators Database Archives** preserve historical editions of WDI. MacroTrace uses public API source `57` to load each edition as a vintage, so the same `as_of()`, vintage-matrix, and `identify_vintage()` operations used for other sources also work with WDI.

Source 57 is public and credential-free. It does not require a World Bank account, API key, cookie, or authorization header.

## Archived editions are not the current-data API

MacroTrace uses this archive route:

```text
/v2/sources/57/country/{country}/series/{indicator}/time/all/version/{edition}/data
```

which is different from the ordinary current-data route:

```text
/v2/country/{country}/indicator/{indicator}
```

On the ordinary route, `date=` selects observation years. It does **not** select a historical WDI database vintage.

## Edition IDs and month-precision timestamps

The archive's exact edition identifier is `YYYYMM`: for example, `200704` is April 2007 and `201407` is July 2014. The source supplies a month, not a verified release day.

MacroTrace preserves the exact edition ID and the source label in release provenance. Because its core vintage model uses timezone-aware timestamps, WDI editions are conservatively represented as **00:00 UTC on the final calendar day of the edition month**. Thus `201407` is represented as `2014-07-31 00:00 UTC`. This avoids making an edition appear available at the start of its month and does not claim that the final day was the actual publication day.

Consequences for date-based operations:

- `as_of("2014-07-30")` excludes edition `201407`.
- `as_of("2014-07-31")` includes edition `201407`.
- Use exact edition retrieval when the source ID, rather than a conservative date boundary, is what matters.

## Finding WDI dataset IDs

For WDI, `dataset_id` is the World Bank indicator code, such as `NY.GDP.PCAP.KD` for GDP per capita in constant US dollars.

The easiest way to find a code by name or topic is the World Bank's [indicator browser](https://data.worldbank.org/indicator). Open an indicator and copy the code from the end of its URL; for example, the page URL `https://data.worldbank.org/indicator/NY.GDP.PCAP.KD` corresponds to `dataset_id="NY.GDP.PCAP.KD"`.

For an archive-specific catalogue, query the World Bank indicator API with source `57`:

```text
https://api.worldbank.org/v2/source/57/indicator?format=json&per_page=1000&page=1
```

The first JSON item contains pagination metadata and the second contains indicator records. Use each record's `id` as the MacroTrace `dataset_id` and its `name` to identify the series. Follow the reported `pages` value to retrieve the complete catalogue; the World Bank's [indicator-query documentation](https://datahelpdesk.worldbank.org/knowledgebase/articles/898599-indicator-api-queries) describes the response and source filtering.

An indicator's presence in the source-57 catalogue does not guarantee observations for every entity or archived edition. After choosing a code, check the editions and entity coverage needed for the analysis.

## Loading one country or economy

Use the WDI indicator code as `dataset_id` and the World Bank entity code as the `country` series dimension:

```python
from macrotrace import MTTimeSeries

series = MTTimeSeries(
    dataset_id="NY.GDP.PCAP.KD",
    source="WDI",
    series_key={"country": "USA"},
    vintage_start_date="2014-04-01",
    vintage_end_date="2014-07-31",
    update_prior_to_load=True,
)

author_vintage = series.as_of("2014-07-31")
matrix = series.generate_vintage_matrix()

# A date-indexed pandas Series copied from an unknown historical extract.
author_data = author_vintage.to_series()
match = series.identify_vintage(author_data)

print(author_vintage.release_date)
print(matrix.shape)
print(match.release_dates)
```

WDI requires `series_key` to be a dictionary containing exactly one country or economy code, for example `{"country": "USA"}`. String shorthand such as `series_key="USA"` is not accepted.

`update_prior_to_load=True` refreshes the edition catalogue and ingests locally missing editions inside the requested vintage window. Each edition is stored as a complete snapshot. MacroTrace does not forward-fill a value that disappears; the corresponding vintage-matrix cell remains missing even if the value returns in a later edition.

## Exact edition retrieval

The low-level client can retrieve an exact edition ID without translating it through a day-level date:

```python
from macrotrace.sources.wdi import WDIAPIClient

client = WDIAPIClient(
    indicator="NY.GDP.PCAP.KD",
    country="USA",
)

editions = client.list_editions()
rows_201407 = client.edition("201407")

print(editions[-1]["edition_id"])
print(rows_201407[0]["edition_id"])
```

`list_editions()` always follows the catalogue pagination and does not assume a fixed number of editions or a hard-coded latest edition.

Each non-null row contains the indicator code and name, source entity code and name, observation year and UTC date, exact edition ID and label, numeric value, source ID and name, request URL, and the original World Bank variable metadata indexed by concept. Null values are normal and are omitted.

## Bulk or panel retrieval

Pass `country="all"` to the low-level client for an edition-wide panel:

```python
import pandas as pd

from macrotrace.sources.wdi import WDIAPIClient

client = WDIAPIClient()
rows = client.fetch_edition(
    "NY.GDP.PCAP.KD",
    "201407",
    country="all",
)
panel = pd.DataFrame(rows)

print(panel[["country_code", "observation_year", "value"]].head())
```

`country/all` can contain aggregates as well as economies. MacroTrace retains the source's entity code, name, and complete entity variable metadata. If the archive row does not classify the entity, `entity_type` is `"unclassified"`; MacroTrace does not silently assert that every code is a country. Filter or classify entities explicitly before treating this result as a country panel.

## Country-code aliases

Historical editions and user datasets may use an older code for the same economy. MacroTrace exposes an explicit bidirectional alias layer for:

| Historical code | Current code |
|-----------------|--------------|
| `ZAR` | `COD` |
| `ROM` | `ROU` |
| `TMP` | `TLS` |

An `MTTimeSeries` load first asks for the requested code and, if that exact edition is empty, tries its paired alias. The stored series key remains the code the user requested. Release provenance records every code queried, every URL, and every source entity code returned, so the mapping is never a silent rewrite. The public `WDI_COUNTRY_ALIASES` and `country_code_candidates()` helpers can be used when reconciling external panels.

The observation identity includes the selected series, release, and observation timestamp so multiple entity slices can coexist. Databases created with an older observation schema are not migrated automatically and must be recreated before loading multidimensional sources such as WDI or ONS.

## Pagination, retries, and cache behavior

The client follows the World Bank response's `page`, `pages`, `per_page`, and `total` fields for both the catalogue and edition data. It validates the two different response shapes: catalogue `source` is a list, while data `source` is an object. Inconsistent totals, wrong page numbers, missing concepts, invalid `YRYYYY` values, and non-numeric non-null observations raise a clear `WDIResponseError`.

Requests use MacroTrace's normal SQLite request cache. The full URL and query parameters form the cache key, including source, indicator, country selection, time selection, edition, page, and page size. The growing edition catalogue uses the normal cache expiry. Immutable historical edition responses do not expire, so repeated loads do not re-download them. Pass `force_refresh=True` to a low-level catalogue or edition call only when a deliberate refresh is required.

HTTP 429, transient 5xx responses, timeouts, and connection failures receive bounded retries. `Retry-After` is honored when supplied. Permanent 4xx errors fail immediately. An edition with zero rows, or only null values, is recorded as a valid completed request rather than treated as corrupt or downloaded again.

## Coverage changes and constant-price rebasing

Country and entity coverage can change non-monotonically across WDI editions. An observation may disappear and later return. Treat each edition as its own snapshot and inspect missing values in the vintage matrix rather than filling them across editions.

Constant-price indicators also require special care. WDI base-year regimes can change between editions, causing large shifts in published **levels** even when growth rates move much less. Before interpreting a level revision as a change in the underlying economy, inspect the indicator definition, units, edition metadata, and any rebasing break.
