import pytest

from macrotrace.sources.user import USER_SOURCE_ADAPTER


def test_user_adapter_normalizes_keys_without_providing_an_updater():
    """Keep user data lightweight and disconnected from external updates."""
    assert USER_SOURCE_ADAPTER.normalize_series_key("CUSTOM", None) == {}
    with pytest.raises(NotImplementedError, match="does not provide"):
        USER_SOURCE_ADAPTER.create_update_manager("CUSTOM", {})
