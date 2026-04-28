import datetime
from peewee import (
    SQL,
    DateTimeField,
    FloatField,
    ForeignKeyField,
    Model,
    TextField,
)
from playhouse.sqlite_ext import SqliteExtDatabase, JSONField
import pandas as pd

LOCAL_DATABASE = SqliteExtDatabase(
    None,
    pragmas=(
        ("cache_size", -1024 * 32),  # 32MB page-cache.
        ("journal_mode", "wal"),
        ("foreign_keys", 1),
    ),
)


def is_valid_dateoffset(value: str) -> bool:
    """
    Checks if a string is a valid pandas date offset.
    We are using this to ensure that frequency fields conform to pandas offset strings.
    Certain export and processing functions depend on this format such as to_darts_timeseries.

    Args:
        value (str): The string to check.

    Returns:
        bool: True if the string is a valid pandas date offset, False otherwise.
    """
    try:
        pd.tseries.frequencies.to_offset(value)
        return True
    except (ValueError, TypeError):
        return False


class StrictDateTimeField(DateTimeField):
    """DateTimeField that enforces timezone-aware datetime objects in ISO 8601 format."""

    def db_value(self, value):
        if value is None:
            return None
        if not isinstance(value, datetime.datetime):
            raise ValueError(f"Value must be a datetime object, got {type(value)}")
        if value.tzinfo is None:
            raise ValueError("Datetime must be timezone-aware (include tzinfo).")
        return value.isoformat()

    def python_value(self, value):
        if value is None:
            return None
        if isinstance(value, datetime.datetime):
            return value
        try:
            # Parse ISO 8601 format
            parsed = datetime.datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                raise ValueError("Parsed datetime is missing timezone information.")
            return parsed
        except (ValueError, AttributeError) as e:
            raise ValueError(
                f"Invalid datetime format. Expected ISO 8601 with timezone: {e}"
            )


class FrequencyField(TextField):
    def db_value(self, value):
        if value is not None and not is_valid_dateoffset(value):
            raise ValueError(f"Invalid pandas frequency offset: {value}")
        return super().db_value(value)


class DataBaseModel(Model):
    class Meta:
        database = LOCAL_DATABASE


class Dataset(DataBaseModel):
    """Identity of a dataset; versioning lives in DatasetVersion."""

    source = TextField()
    dataset_id = TextField()

    class Meta:
        constraints = [SQL("UNIQUE(source, dataset_id)")]

    def __repr__(self):
        return f"Dataset(source={self.source}, dataset_id={self.dataset_id})"


class DatasetDimension(DataBaseModel):
    """
    Identity of a dataset dimension.
    """

    dataset = ForeignKeyField(
        Dataset,
        backref="dimensions",
        on_delete="CASCADE",
    )
    # This is the ID used by the source to identify the dimension
    # This should NOT change as the dimension is versioned via valid_from and valid_to
    dataset_dimension_id = TextField()
    title = TextField()
    type = TextField(
        choices=[
            ("text", "text"),
            ("numeric", "numeric"),
            ("boolean", "boolean"),
        ]
    )
    frequency = FrequencyField(null=True)
    description = TextField(null=True)
    units = TextField(null=True)
    seasonal_adjustment = TextField(null=True)
    # Validity period for this dimension definition, null valid_to means currently valid
    valid_from = StrictDateTimeField()
    valid_to = StrictDateTimeField(null=True)
    created_at = StrictDateTimeField(
        default=datetime.datetime.now(tz=datetime.timezone.utc)
    )

    class Meta:
        constraints = [
            SQL("UNIQUE(dataset_id, dataset_dimension_id, valid_from)"),
            SQL("CHECK(type IN ('text', 'numeric', 'boolean'))"),
            SQL("CHECK(valid_to IS NULL OR valid_to > valid_from)"),
        ]

    def __repr__(self):
        return (
            f"DatasetDimension(dataset={self.dataset.dataset_id}, title={self.title})"
        )


class Release(DataBaseModel):
    """
    A release of data in a dataset at a point in time.
    It is not versioned itself as releases are theoretically immutable once created.
    """

    dataset = ForeignKeyField(
        Dataset,
        backref="releases",
        on_delete="CASCADE",
    )
    release_date = StrictDateTimeField()
    additional_metadata = JSONField(null=True)
    created_at = StrictDateTimeField(
        default=datetime.datetime.now(tz=datetime.timezone.utc)
    )

    class Meta:
        constraints = [SQL("UNIQUE(dataset_id, release_date)")]

    def __repr__(self):
        return (
            f"Release(dataset={self.dataset.dataset_id}, "
            f"release_date={self.release_date})"
        )


class ReleaseDimension(DataBaseModel):
    """
    Association table for many-to-many relationship between Release and DatasetDimension.
    Tracks which dimensions are included in each release.
    """

    release = ForeignKeyField(
        Release,
        backref="release_dimensions",
        on_delete="CASCADE",
    )
    dimension = ForeignKeyField(
        DatasetDimension,
        backref="release_dimensions",
        on_delete="CASCADE",
    )
    created_at = StrictDateTimeField(
        default=datetime.datetime.now(tz=datetime.timezone.utc)
    )

    class Meta:
        constraints = [SQL("UNIQUE(release_id, dimension_id)")]

    def __repr__(self):
        return (
            f"ReleaseDimension(release={self.release.release_date}, "
            f"dimension={self.dimension.title})"
        )


class Series(DataBaseModel):
    dataset = ForeignKeyField(Dataset, backref="series", on_delete="CASCADE")
    series_key = JSONField()
    created_at = StrictDateTimeField(
        default=datetime.datetime.now(tz=datetime.timezone.utc)
    )

    def __repr__(self):
        return (
            f"Series(dataset = {self.dataset.dataset_id}, series_key={self.series_key})"
        )


class SeriesDimensionFilter(DataBaseModel):
    series = ForeignKeyField(
        Series,
        backref="dimension_selections",
        on_delete="CASCADE",
    )
    dimension = ForeignKeyField(
        DatasetDimension,
        on_delete="CASCADE",
    )
    # For numeric or boolean dimensions
    # Store as text, cast as needed based on dimension.type
    value = TextField()

    class Meta:
        constraints = [
            SQL("UNIQUE(series_id, dimension_id, value)"),
        ]

    def __repr__(self):
        return (
            f"SeriesDimensionFilter(series={self.series.series_key}, "
            f"dimension={self.dimension.title}, value={self.value})"
        )


class Observation(DataBaseModel):
    series = ForeignKeyField(
        Series,
        backref="observations",
        on_delete="CASCADE",
    )
    release = ForeignKeyField(
        Release,
        backref="observations",
        on_delete="CASCADE",
    )

    observation_timestamp = StrictDateTimeField()
    value = FloatField(null=True)  # null if the observation is missing
    created_at = StrictDateTimeField(
        default=datetime.datetime.now(tz=datetime.timezone.utc)
    )

    class Meta:
        constraints = [SQL("UNIQUE(release_id, observation_timestamp)")]

    def __repr__(self):
        return (
            f"Observation(series={self.series.series_key}, "
            f"release={self.release.release_date}, "
            f"observation_timestamp={self.observation_timestamp}, "
            f"value={self.value})"
        )
