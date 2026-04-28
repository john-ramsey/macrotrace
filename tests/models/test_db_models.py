import pytest
import datetime
from peewee import *
from macrotrace.models.db import (
    Dataset,
    DatasetDimension,
    Release,
    ReleaseDimension,
    Series,
    SeriesDimensionFilter,
    Observation,
    StrictDateTimeField,
)

# Create a test database (in-memory)
db = SqliteDatabase(":memory:")
UTC = datetime.timezone.utc


@pytest.fixture(scope="function", autouse=True)
def db_setup_and_teardown():
    # Bind models to test DB
    models = [
        Dataset,
        DatasetDimension,
        Release,
        ReleaseDimension,
        Series,
        SeriesDimensionFilter,
        Observation,
    ]
    db.bind(models, bind_refs=False, bind_backrefs=False)
    db.connect(reuse_if_open=True)
    db.create_tables(models)

    yield

    db.drop_tables(models)
    db.close()


@pytest.fixture
def sample_dataset():
    """Create a sample dataset for testing."""
    return Dataset.create(
        source="TEST_SOURCE",
        dataset_id="TEST_DATASET_001",
    )


@pytest.fixture
def sample_dimension(sample_dataset):
    """Create a sample dimension for testing."""
    return DatasetDimension.create(
        dataset=sample_dataset,
        dataset_dimension_id="FREQ",
        title="Frequency",
        type="text",
        frequency="MS",
        description="Data frequency",
        valid_from=datetime.datetime(2020, 1, 1, tzinfo=UTC),
    )


def test_dataset_creation():
    """Test basic dataset creation."""
    ds = Dataset.create(
        source="BEA",
        dataset_id="NIPA",
    )

    assert ds.source == "BEA"
    assert ds.dataset_id == "NIPA"
    assert isinstance(ds.id, int)


def test_dataset_uniqueness():
    """Test that duplicate datasets cannot be created."""
    Dataset.create(source="FRED", dataset_id="GDP")

    with pytest.raises(IntegrityError):
        Dataset.create(source="FRED", dataset_id="GDP")


def test_dataset_repr():
    """Test dataset repr method."""
    ds = Dataset.create(source="BLS", dataset_id="CPI")
    assert repr(ds) == "Dataset(source=BLS, dataset_id=CPI)"


def test_dimension_creation(sample_dataset):
    """Test basic dimension creation."""
    dim = DatasetDimension.create(
        dataset=sample_dataset,
        dataset_dimension_id="UNIT",
        title="Units",
        type="text",
        frequency="MS",
        description="Measurement units",
        units="Index",
        seasonal_adjustment="Seasonally Adjusted",
        valid_from=datetime.datetime(2020, 1, 1, tzinfo=UTC),
    )

    assert dim.dataset_dimension_id == "UNIT"
    assert dim.title == "Units"
    assert dim.type == "text"
    assert dim.units == "Index"
    assert dim.seasonal_adjustment == "Seasonally Adjusted"
    assert isinstance(dim.id, int)


def test_dimension_type_choices(sample_dataset):
    """Test that valid dimension types can be created."""
    valid_types = ["text", "numeric", "boolean"]

    for idx, dim_type in enumerate(valid_types):
        dim = DatasetDimension.create(
            dataset=sample_dataset,
            dataset_dimension_id=f"DIM_{idx}",
            title=f"Dimension {idx}",
            frequency="MS",
            type=dim_type,
            valid_from=datetime.datetime(2020, 1, 1, tzinfo=UTC),
        )
        assert dim.type == dim_type


def test_dimension_frequencies(sample_dataset):
    """Test that valid dimension frequencies can be created."""
    common_pandas_offset_frequencies = [
        "D",
        "W",
        "MS",
        "QS",
        "YS",
        "h",
        "2QS",
        "5YS",
        "3MS",
    ]

    for idx, freq in enumerate(common_pandas_offset_frequencies):
        dim = DatasetDimension.create(
            dataset=sample_dataset,
            dataset_dimension_id=f"FREQ_{idx}",
            title=f"Frequency Dimension {idx}",
            type="text",
            frequency=freq,
            valid_from=datetime.datetime(2020, 1, 1, tzinfo=UTC),
        )
        assert dim.frequency == freq


def test_dimension_invalid_frequency(sample_dataset):
    """Test that invalid dimension frequencies raise an error."""
    with pytest.raises(ValueError):
        DatasetDimension.create(
            dataset=sample_dataset,
            dataset_dimension_id="INVALID_FREQ",
            title="Invalid Frequency Dimension",
            type="text",
            frequency="InvalidFreq",
            valid_from=datetime.datetime(2020, 1, 1, tzinfo=UTC),
        )


def test_dimension_invalid_type(sample_dataset):
    """Test that invalid dimension types raise an error."""
    with pytest.raises(IntegrityError):
        DatasetDimension.create(
            dataset=sample_dataset,
            dataset_dimension_id="INVALID_DIM",
            title="Invalid Dimension",
            type="invalid_type",
            valid_from=datetime.datetime(2020, 1, 1, tzinfo=UTC),
        )


def test_dimension_uniqueness(sample_dataset):
    """Test that duplicate dimensions with same valid_from cannot be created."""
    valid_from = datetime.datetime(2020, 1, 1, tzinfo=UTC)

    dim_dict = {
        "dataset": sample_dataset,
        "dataset_dimension_id": "LOCATION",
        "title": "Location",
        "type": "text",
        "frequency": "MS",
        "valid_from": valid_from,
    }

    DatasetDimension.create(**dim_dict)

    with pytest.raises(IntegrityError):
        DatasetDimension.create(**dim_dict)


def test_dimension_versioning(sample_dataset):
    """Test that dimensions can be versioned with different valid_from dates."""
    dim1 = DatasetDimension.create(
        dataset=sample_dataset,
        dataset_dimension_id="GEO",
        title="Geography v1",
        type="text",
        frequency="MS",
        valid_from=datetime.datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=datetime.datetime(2021, 12, 31, tzinfo=UTC),
    )

    dim2 = DatasetDimension.create(
        dataset=sample_dataset,
        dataset_dimension_id="GEO",
        title="Geography v2",
        type="text",
        frequency="MS",
        valid_from=datetime.datetime(2022, 1, 1, tzinfo=UTC),
    )

    assert dim1.title == "Geography v1"
    assert dim2.title == "Geography v2"
    assert dim1.valid_to is not None
    assert dim2.valid_to is None
    assert dim1.id != dim2.id


def test_dimension_repr(sample_dimension):
    """Test dimension repr method."""
    assert (
        repr(sample_dimension)
        == f"DatasetDimension(dataset={sample_dimension.dataset.dataset_id}, title={sample_dimension.title})"
    )


def test_release_creation(sample_dataset):
    """Test basic release creation."""
    release = Release.create(
        dataset=sample_dataset,
        release_date=datetime.datetime(2022, 6, 1, tzinfo=UTC),
        additional_metadata={"source": "API", "version": "1.0"},
    )

    assert release.dataset == sample_dataset
    assert release.release_date == datetime.datetime(2022, 6, 1, tzinfo=UTC)
    assert release.additional_metadata["source"] == "API"
    assert isinstance(release.id, int)


def test_release_uniqueness(sample_dataset):
    """Test that duplicate releases cannot be created for the same dataset and date."""
    release_date = datetime.datetime(2023, 1, 1, tzinfo=UTC)

    Release.create(
        dataset=sample_dataset,
        release_date=release_date,
    )

    with pytest.raises(IntegrityError):
        Release.create(
            dataset=sample_dataset,
            release_date=release_date,
        )


def test_release_repr(sample_dataset):
    """Test release repr method."""
    release = Release.create(
        dataset=sample_dataset,
        release_date=datetime.datetime(2022, 1, 1, tzinfo=UTC),
    )
    assert (
        repr(release)
        == f"Release(dataset={sample_dataset.dataset_id}, release_date={release.release_date})"
    )


def test_release_dimension_creation(sample_dataset, sample_dimension):
    """Test creating release-dimension associations."""
    release = Release.create(
        dataset=sample_dataset,
        release_date=datetime.datetime(2022, 1, 1, tzinfo=UTC),
    )

    rel_dim = ReleaseDimension.create(
        release=release,
        dimension=sample_dimension,
    )

    assert rel_dim.release == release
    assert rel_dim.dimension == sample_dimension
    assert isinstance(rel_dim.id, int)


def test_release_dimension_uniqueness(sample_dataset, sample_dimension):
    """Test that duplicate release-dimension associations cannot be created."""
    release = Release.create(
        dataset=sample_dataset,
        release_date=datetime.datetime(2022, 1, 1, tzinfo=UTC),
    )

    ReleaseDimension.create(
        release=release,
        dimension=sample_dimension,
    )

    with pytest.raises(IntegrityError):
        ReleaseDimension.create(
            release=release,
            dimension=sample_dimension,
        )


def test_release_dimension_repr(sample_dataset, sample_dimension):
    """Test release dimension repr method."""
    release = Release.create(
        dataset=sample_dataset,
        release_date=datetime.datetime(2022, 1, 1, tzinfo=UTC),
    )
    rel_dim = ReleaseDimension.create(
        release=release,
        dimension=sample_dimension,
    )
    assert (
        repr(rel_dim)
        == f"ReleaseDimension(release={release.release_date}, dimension={sample_dimension.title})"
    )


def test_series_creation(sample_dataset):
    """Test basic series creation."""
    series = Series.create(
        dataset=sample_dataset,
        series_key={"frequency": "MS", "geo": "US", "indicator": "GDP"},
    )

    assert series.dataset == sample_dataset
    assert series.series_key["frequency"] == "MS"
    assert series.series_key["geo"] == "US"
    assert isinstance(series.id, int)


def test_series_repr(sample_dataset):
    """Test series repr method."""
    series = Series.create(
        dataset=sample_dataset,
        series_key={"frequency": "MS", "geo": "US", "indicator": "CPI"},
    )
    assert (
        repr(series)
        == f"Series(dataset = {series.dataset.dataset_id}, series_key={series.series_key})"
    )


def test_series_dimension_filter_creation(sample_dataset, sample_dimension):
    """Test creating series dimension filters."""
    series = Series.create(
        dataset=sample_dataset,
        series_key={"frequency": "Quarterly"},
    )

    filter_obj = SeriesDimensionFilter.create(
        series=series,
        dimension=sample_dimension,
        value="Quarterly",
    )

    assert filter_obj.series == series
    assert filter_obj.dimension == sample_dimension
    assert filter_obj.value == "Quarterly"
    assert isinstance(filter_obj.id, int)


def test_series_dimension_filter_uniqueness(sample_dataset, sample_dimension):
    """Test that duplicate series dimension filters cannot be created."""
    series = Series.create(
        dataset=sample_dataset,
        series_key={"test": "value"},
    )

    SeriesDimensionFilter.create(
        series=series,
        dimension=sample_dimension,
        value="MS",
    )

    with pytest.raises(IntegrityError):
        SeriesDimensionFilter.create(
            series=series,
            dimension=sample_dimension,
            value="MS",
        )


def test_series_dimension_filter_repr(sample_dataset, sample_dimension):
    """Test series dimension filter repr method."""
    series = Series.create(
        dataset=sample_dataset,
        series_key={"test": "value"},
    )

    filter_obj = SeriesDimensionFilter.create(
        series=series,
        dimension=sample_dimension,
        value="TestValue",
    )

    assert repr(filter_obj) == (
        f"SeriesDimensionFilter(series={filter_obj.series.series_key}, "
        f"dimension={filter_obj.dimension.title}, value={filter_obj.value})"
    )


def test_observation_creation(sample_dataset):
    """Test basic observation creation."""
    series = Series.create(
        dataset=sample_dataset,
        series_key={"indicator": "UNRATE"},
    )

    release = Release.create(
        dataset=sample_dataset,
        release_date=datetime.datetime(2022, 6, 1, tzinfo=UTC),
    )

    obs = Observation.create(
        series=series,
        release=release,
        observation_timestamp=datetime.datetime(2022, 5, 1, tzinfo=UTC),
        value=3.8,
    )

    assert obs.value == 3.8
    assert obs.series == series
    assert obs.release == release
    assert isinstance(obs.id, int)


def test_observation_linking(sample_dataset):
    """Test that observations link properly to series and releases."""
    series = Series.create(
        dataset=sample_dataset,
        series_key={"indicator": "GDP"},
    )

    release = Release.create(
        dataset=sample_dataset,
        release_date=datetime.datetime(2022, 6, 1, tzinfo=UTC),
    )

    obs = Observation.create(
        series=series,
        release=release,
        observation_timestamp=datetime.datetime(2022, 5, 1, tzinfo=UTC),
        value=21500.0,
    )

    assert obs.series.dataset == sample_dataset
    assert obs.release.dataset == sample_dataset


def test_observation_uniqueness_constraint(sample_dataset):
    """Test that duplicate observations for the same release and timestamp cannot be created."""
    series = Series.create(
        dataset=sample_dataset,
        series_key={"indicator": "PAYEMS"},
    )

    release = Release.create(
        dataset=sample_dataset,
        release_date=datetime.datetime(2023, 1, 1, tzinfo=UTC),
    )

    obs_timestamp = datetime.datetime(2023, 4, 1, tzinfo=UTC)

    Observation.create(
        series=series,
        release=release,
        observation_timestamp=obs_timestamp,
        value=145000,
    )

    with pytest.raises(IntegrityError):
        Observation.create(
            series=series,
            release=release,
            observation_timestamp=obs_timestamp,
            value=146000,
        )


def test_observation_null_value(sample_dataset):
    """Test that observations can have null values."""
    series = Series.create(
        dataset=sample_dataset,
        series_key={"indicator": "MISSING_DATA"},
    )

    release = Release.create(
        dataset=sample_dataset,
        release_date=datetime.datetime(2022, 1, 1, tzinfo=UTC),
    )

    obs = Observation.create(
        series=series,
        release=release,
        observation_timestamp=datetime.datetime(2022, 1, 1, tzinfo=UTC),
        value=None,
    )

    assert obs.value is None


def test_observation_repr(sample_dataset):
    """Test observation repr method."""
    series = Series.create(
        dataset=sample_dataset,
        series_key={"indicator": "CPI"},
    )

    release = Release.create(
        dataset=sample_dataset,
        release_date=datetime.datetime(2022, 1, 1, tzinfo=UTC),
    )

    obs = Observation.create(
        series=series,
        release=release,
        observation_timestamp=datetime.datetime(2022, 1, 1, tzinfo=UTC),
        value=250.5,
    )

    expected = (
        f"Observation(series={series.series_key}, "
        f"release={release.release_date}, "
        f"observation_timestamp={obs.observation_timestamp}, "
        f"value={obs.value})"
    )
    assert repr(obs) == expected


def test_strict_datetime_field_stores_timezone_aware_datetime(sample_dataset):
    """Test that StrictDateTimeField stores and retrieves timezone-aware datetimes."""
    dt = datetime.datetime(2023, 6, 15, 14, 30, 0, tzinfo=UTC)
    release = Release.create(
        dataset=sample_dataset,
        release_date=dt,
    )

    retrieved = Release.get_by_id(release.id)
    assert retrieved.release_date == dt


def test_strict_datetime_field_handles_timezone_offset(sample_dataset):
    """Test that StrictDateTimeField handles non-UTC timezone offsets."""
    tz = datetime.timezone(datetime.timedelta(hours=-5))
    dt = datetime.datetime(2023, 6, 15, 14, 30, 0, tzinfo=tz)
    release = Release.create(
        dataset=sample_dataset,
        release_date=dt,
    )

    retrieved = Release.get_by_id(release.id)
    assert retrieved.release_date == dt
    assert retrieved.release_date.tzinfo == tz


def test_strict_datetime_field_rejects_timezone_naive_datetime(sample_dataset):
    """Test that StrictDateTimeField rejects timezone-naive datetimes."""
    dt_naive = datetime.datetime(2023, 6, 15, 14, 30, 0)

    with pytest.raises(ValueError, match="Datetime must be timezone-aware"):
        Release.create(
            dataset=sample_dataset,
            release_date=dt_naive,
        )


def test_strict_datetime_field_rejects_non_datetime_value(sample_dataset):
    """Test that StrictDateTimeField rejects non-datetime values."""
    with pytest.raises(ValueError, match="Value must be a datetime object"):
        Release.create(
            dataset=sample_dataset,
            release_date="2023-06-15T14:30:00+00:00",
        )


def test_strict_datetime_field_db_value_returns_iso_format():
    """Test that StrictDateTimeField.db_value converts to ISO 8601 format."""
    field = StrictDateTimeField()
    dt = datetime.datetime(2023, 6, 15, 14, 30, 0, tzinfo=UTC)

    result = field.db_value(dt)
    assert result == "2023-06-15T14:30:00+00:00"


def test_strict_datetime_field_db_value_returns_none_for_none():
    """Test that StrictDateTimeField.db_value returns None for None input."""
    field = StrictDateTimeField()
    assert field.db_value(None) is None


def test_strict_datetime_field_python_value_parses_iso_string():
    """Test that StrictDateTimeField.python_value parses ISO 8601 strings."""
    field = StrictDateTimeField()
    iso_string = "2023-06-15T14:30:00+00:00"

    result = field.python_value(iso_string)
    expected = datetime.datetime(2023, 6, 15, 14, 30, 0, tzinfo=UTC)
    assert result == expected


def test_strict_datetime_field_python_value_parses_iso_with_offset():
    """Test that StrictDateTimeField.python_value parses ISO strings with timezone offset."""
    field = StrictDateTimeField()
    iso_string = "2023-06-15T14:30:00-05:00"

    result = field.python_value(iso_string)
    tz = datetime.timezone(datetime.timedelta(hours=-5))
    expected = datetime.datetime(2023, 6, 15, 14, 30, 0, tzinfo=tz)
    assert result == expected


def test_strict_datetime_field_python_value_handles_datetime_passthrough():
    """Test that StrictDateTimeField.python_value returns datetime objects unchanged."""
    field = StrictDateTimeField()
    dt = datetime.datetime(2023, 6, 15, 14, 30, 0, tzinfo=UTC)

    result = field.python_value(dt)
    assert result == dt
    assert result is dt


def test_strict_datetime_field_python_value_returns_none_for_none():
    """Test that StrictDateTimeField.python_value returns None for None input."""
    field = StrictDateTimeField()
    assert field.python_value(None) is None


def test_strict_datetime_field_python_value_rejects_invalid_format():
    """Test that StrictDateTimeField.python_value rejects invalid datetime strings."""
    field = StrictDateTimeField()

    with pytest.raises(ValueError, match="Invalid datetime format"):
        field.python_value("2023-06-15 14:30:00")


def test_strict_datetime_field_python_value_rejects_non_iso_string():
    """Test that StrictDateTimeField.python_value rejects non-ISO strings."""
    field = StrictDateTimeField()

    with pytest.raises(ValueError, match="Invalid datetime format"):
        field.python_value("not a date")


def test_strict_datetime_field_round_trip_conversion():
    """Test that datetime values survive db_value -> python_value round trip."""
    field = StrictDateTimeField()
    original = datetime.datetime(2023, 6, 15, 14, 30, 0, 123456, tzinfo=UTC)

    db_val = field.db_value(original)
    restored = field.python_value(db_val)

    assert restored == original
