from datetime import datetime, tzinfo
from typing import Optional


def ensure_timezone(dt: Optional[datetime], tz: tzinfo) -> Optional[datetime]:
    """
    Return the datetime made aware in ``tz``, or None.

    Naive datetimes keep their wall clock while aware ones are converted. Uses pytz's
    ``localize()`` when available so the real historical offset is picked
    instead of pytz's first entry for the zone (LMT).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        if hasattr(tz, "localize"):
            return tz.localize(dt)
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)
