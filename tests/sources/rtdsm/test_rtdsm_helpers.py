import pytest
from datetime import datetime, timezone
import pytz

from macrotrace.sources import rtdsm as R

# Importing the db fixture keeps the test module consistent with the others,
# though the pure helpers below do not touch the database.
from tests.sources.rtdsm.fixtures import db_setup_and_teardown, make_xlsx_bytes

UTC = pytz.timezone("UTC")


def test_catalog_is_complete_and_consistent():
    """The bundled catalog has 115 series with valid frequencies."""
    assert len(R.RTDSM_CATALOG) == 115
    for dataset_id, info in R.RTDSM_CATALOG.items():
        assert dataset_id == dataset_id.upper()
        assert info.data_freq in ("M", "Q")
        assert info.vintage_freqs  # non-empty
        assert set(info.vintage_freqs) <= {"M", "Q"}


def test_build_filename_is_lowercase():
    assert R._build_filename("ROUTPUT", "Q", "Q") == "routputqvqd.xlsx"
    assert R._build_filename("RCON", "M", "Q") == "rconmvqd.xlsx"
    assert R._build_filename("CPI", "Q", "M") == "cpiqvmd.xlsx"


def test_first_of_next_month_mid_year():
    assert R._first_of_next_month(datetime(2026, 1, 15, tzinfo=UTC)) == datetime(
        2026, 2, 1, tzinfo=UTC
    )


def test_first_of_next_month_december_rolls_year():
    assert R._first_of_next_month(datetime(2026, 12, 9, tzinfo=UTC)) == datetime(
        2027, 1, 1, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "label,dataset_id,expected",
    [
        ("ROUTPUT65Q4", "ROUTPUT", datetime(1965, 11, 15, tzinfo=UTC)),
        ("ROUTPUT66Q1", "ROUTPUT", datetime(1966, 2, 15, tzinfo=UTC)),
        ("RCON65M11", "RCON", datetime(1965, 11, 15, tzinfo=UTC)),
        ("RCON26M6", "RCON", datetime(2026, 6, 15, tzinfo=UTC)),
        # Mnemonics that themselves contain digits must still parse.
        ("M180Q2", "M1", datetime(1980, 5, 15, tzinfo=UTC)),
        ("M205M3", "M2", datetime(2005, 3, 15, tzinfo=UTC)),
        # Monthly-vintage series whose history begins before 1965 must be
        # dated in the 1900s (IPM/IPT start at 1962:M11, EMPLOY at 1964:M12).
        ("EMPLOY64M12", "EMPLOY", datetime(1964, 12, 15, tzinfo=UTC)),
        ("IPM62M11", "IPM", datetime(1962, 11, 15, tzinfo=UTC)),
        ("IPT62M12", "IPT", datetime(1962, 12, 15, tzinfo=UTC)),
    ],
)
def test_parse_vintage_label(label, dataset_id, expected):
    assert R._parse_vintage_label(label, dataset_id, current_year=2026) == expected


def test_parse_vintage_label_year_resolution():
    """
    Two-digit years resolve relative to the reference year; a reading that
    would land in the future falls back to the 1900s, so pre-1965 vintages are
    dated correctly without a fixed pivot.
    """
    p = R._parse_vintage_label
    assert p("ROUTPUT99Q1", "ROUTPUT", current_year=2026).year == 1999
    assert p("ROUTPUT00Q1", "ROUTPUT", current_year=2026).year == 2000
    assert p("ROUTPUT64Q1", "ROUTPUT", current_year=2026).year == 1964
    assert p("ROUTPUT26Q1", "ROUTPUT", current_year=2026).year == 2026
    # The boundary tracks the reference year rather than a constant.
    assert p("EMPLOY64M12", "EMPLOY", current_year=2070).year == 2064


def test_parse_vintage_label_invalid():
    with pytest.raises(ValueError, match="Unrecognized RTDSM vintage label"):
        R._parse_vintage_label("NOTAVINTAGE", "ROUTPUT")
    with pytest.raises(ValueError, match="Invalid quarter"):
        R._parse_vintage_label("ROUTPUT65Q5", "ROUTPUT")
    with pytest.raises(ValueError, match="Invalid month"):
        R._parse_vintage_label("RCON65M13", "RCON")


@pytest.mark.parametrize(
    "label,freq,expected",
    [
        ("1947:Q1", "Q", datetime(1947, 1, 1, tzinfo=UTC)),
        ("1947:Q4", "Q", datetime(1947, 10, 1, tzinfo=UTC)),
        ("1989:05", "M", datetime(1989, 5, 1, tzinfo=UTC)),
        ("2020:12", "M", datetime(2020, 12, 1, tzinfo=UTC)),
    ],
)
def test_parse_observation_label(label, freq, expected):
    assert R._parse_observation_label(label, freq) == expected


def test_parse_observation_label_invalid():
    with pytest.raises(ValueError, match="quarterly observation label"):
        R._parse_observation_label("1947:13", "Q")
    with pytest.raises(ValueError, match="monthly observation label"):
        R._parse_observation_label("1947:Q1", "M")
    with pytest.raises(ValueError, match="Invalid month"):
        R._parse_observation_label("1947:13", "M")


def test_coerce_value():
    assert R._coerce_value(306.4) == 306.4
    assert R._coerce_value(10) == 10.0
    assert R._coerce_value("#N/A") is None
    assert R._coerce_value("") is None
    assert R._coerce_value(None) is None
    assert R._coerce_value(True) is None  # bool is not a measurement
    assert R._coerce_value(float("nan")) is None


def test_resolve_vintage_freq_default():
    """
    With no request, single-frequency series use their one frequency; dual
    default to quarterly.
    """
    assert R._resolve_vintage_freq("EMPLOY", R.RTDSM_CATALOG["EMPLOY"], None) == "M"
    assert R._resolve_vintage_freq("CPI", R.RTDSM_CATALOG["CPI"], None) == "Q"
    assert R._resolve_vintage_freq("RCON", R.RTDSM_CATALOG["RCON"], None) == "Q"


def test_resolve_vintage_freq_explicit():
    assert R._resolve_vintage_freq("RCON", R.RTDSM_CATALOG["RCON"], "m") == "M"
    assert R._resolve_vintage_freq("RCON", R.RTDSM_CATALOG["RCON"], "Q") == "Q"


def test_resolve_vintage_freq_unavailable_raises():
    with pytest.raises(ValueError, match="does not offer M-frequency"):
        R._resolve_vintage_freq("DIV", R.RTDSM_CATALOG["DIV"], "M")


def test_resolve_vintage_freq_bad_value_raises():
    with pytest.raises(ValueError, match="must be 'Q' or 'M'"):
        R._resolve_vintage_freq("RCON", R.RTDSM_CATALOG["RCON"], "weekly")


def test_ensure_utc():
    naive = datetime(2020, 1, 1)
    assert R._ensure_utc(naive) == datetime(2020, 1, 1, tzinfo=UTC)
    aware = datetime(2020, 1, 1, tzinfo=timezone(timezone.utc.utcoffset(None)))
    assert R._ensure_utc(aware).tzinfo == UTC
    assert R._ensure_utc(None) is None


def test_parse_workbook_quarterly():
    """A quarterly-data workbook parses vintages, observations, and drops #N/A."""
    content = make_xlsx_bytes(
        ["DATE", "ROUTPUT65Q4", "ROUTPUT66Q1"],
        [
            ["1947:Q1", 306.4, 306.4],
            ["1947:Q2", 309.0, 309.0],
            ["1947:Q3", "#N/A", 310.0],
        ],
    )
    parsed = R._parse_workbook(content, "ROUTPUT", "Q")
    assert [label for label, _ in parsed.vintages] == ["ROUTPUT65Q4", "ROUTPUT66Q1"]
    assert parsed.vintages[0][1] == datetime(1965, 11, 15, tzinfo=UTC)
    # The #N/A cell is dropped, so the first vintage has 2 obs, the second 3.
    assert len(parsed.cells["ROUTPUT65Q4"]) == 2
    assert len(parsed.cells["ROUTPUT66Q1"]) == 3
    assert dict(parsed.cells["ROUTPUT66Q1"])[datetime(1947, 7, 1, tzinfo=UTC)] == 310.0


def test_parse_workbook_skips_blank_and_gap_columns():
    """Blank header columns and blank observation labels are ignored."""
    content = make_xlsx_bytes(
        ["DATE", "ROUTPUT65Q4", None],
        [
            ["1947:Q1", 306.4, 999.0],
            [None, 1.0, 2.0],
        ],
    )
    parsed = R._parse_workbook(content, "ROUTPUT", "Q")
    assert [label for label, _ in parsed.vintages] == ["ROUTPUT65Q4"]
    assert len(parsed.cells["ROUTPUT65Q4"]) == 1  # blank-label row skipped


def test_parse_workbook_monthly_data():
    """A monthly-data workbook parses monthly observation labels (YYYY:MM)."""
    content = make_xlsx_bytes(
        ["DATE", "PCPI65M1", "PCPI65M2"],
        [
            ["1947:01", 23.5, 23.5],
            ["1947:02", 23.6, 23.7],
        ],
    )
    parsed = R._parse_workbook(content, "PCPI", "M")
    assert parsed.vintages[0][1] == datetime(1965, 1, 15, tzinfo=UTC)
    cells = dict(parsed.cells["PCPI65M2"])
    assert cells[datetime(1947, 1, 1, tzinfo=UTC)] == 23.5
    assert cells[datetime(1947, 2, 1, tzinfo=UTC)] == 23.7


def test_parse_workbook_dates_pre_1965_vintages():
    """The full parse path dates a pre-1965 monthly vintage in the 1900s."""
    content = make_xlsx_bytes(
        ["DATE", "EMPLOY64M12", "EMPLOY65M1"],
        [["1947:01", 43000.0, 43100.0]],
    )
    parsed = R._parse_workbook(content, "EMPLOY", "M")
    dates = [release_date for _, release_date in parsed.vintages]
    assert dates == [
        datetime(1964, 12, 15, tzinfo=UTC),
        datetime(1965, 1, 15, tzinfo=UTC),
    ]


def test_parse_workbook_empty_raises():
    content = make_xlsx_bytes([], [])
    with pytest.raises(ValueError, match="no rows"):
        R._parse_workbook(content, "ROUTPUT", "Q")
