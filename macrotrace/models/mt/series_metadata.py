from datetime import date
from dataclasses import dataclass
from typing import Dict
import logging
import pandas as pd


@dataclass
class MTSeriesMetadata:
    dataset_id: str
    source: str
    title: str
    realtime_start: date
    realtime_end: date
    observation_start: date
    observation_end: date
    frequency: str
    units: str
    seasonal_adjustment: str
    series_key: Dict[str, str] | None = None

    def __repr__(self) -> str:
        """
        Returns a string representation of the series metadata.

        Returns:
            str: String representation of the series metadata.
        """
        return (
            f"Dataset ID: {self.dataset_id}\n"
            f"Title: {self.title}\n"
            f"Source: {self.source}\n"
            f"Units: {self.units}\n"
            f"Frequency: {self.frequency}\n"
            f"Realtime Range: {self.realtime_start} to {self.realtime_end}\n"
            f"Observation Range: {self.observation_start} to {self.observation_end}\n"
            f"Seasonal Adjustment: {self.seasonal_adjustment}\n"
            f"Series Key: {self.series_key}"
        )

    def get_frequency_as_numeric(self) -> int:
        """
        Converts the frequency string to a numeric value representing the number of periods per year.

        Returns:
            int: Number of periods per year based on the frequency.
        """
        idx = pd.date_range(
            start="2000-01-01", end="2000-12-31", freq=self.frequency
        ).size

        if idx <= 1:
            logging.warning(
                f"Frequency '{self.frequency}' occurs {idx} time(s) in a year. Returning 1 as the numeric frequency."
            )
            return 1
        else:
            logging.info(
                f"Frequency '{self.frequency}' occurs {idx} time(s) in a year. Returning {idx} as the assumed numeric frequency."
            )
            return idx
