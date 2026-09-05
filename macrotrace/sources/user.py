"""Adapter for user-provided time series."""

from datetime import timezone

from macrotrace.sources.base import SourceAdapter

USER_SOURCE = "USER"


class UserSourceAdapter(SourceAdapter):
    """Describe user-provided data, which has no external updater."""

    source = USER_SOURCE
    native_observation_timezone = timezone.utc


USER_SOURCE_ADAPTER = UserSourceAdapter()
