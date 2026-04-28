from datetime import datetime
from dataclasses import dataclass


@dataclass
class MTObservation:
    timestamp: datetime
    value: float
    release_date: datetime
