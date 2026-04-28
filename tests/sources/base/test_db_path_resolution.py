"""Verify ``UpdateManager._ensure_db_initialized`` honors the path resolver."""

from typing import Any, Dict, Optional

from macrotrace._paths import DB_ENV_VAR
from macrotrace.models.db import LOCAL_DATABASE
from macrotrace.sources.base import (
    APIClient,
    DatasetManager,
    ObservationManager,
    ReleaseManager,
    SeriesManager,
    UpdateManager,
)


class _NoopUpdateManager(UpdateManager):
    """Minimal UpdateManager that builds collaborators without hitting the network."""

    def _create_api_client(
        self,
        cache_settings: Optional[Dict[str, Any]] = None,
        cache_path: Optional[str] = None,
    ) -> APIClient:
        client = APIClient(
            base_url="https://example.invalid/",
            cache_settings={"caching": False},
        )
        return client

    def _create_dataset_manager(self) -> DatasetManager:
        return DatasetManager(self.api_client)

    def _create_release_manager(self) -> ReleaseManager:
        return ReleaseManager(self.api_client)

    def _create_series_manager(self) -> SeriesManager:
        return SeriesManager(self.api_client)

    def _create_observation_manager(self) -> ObservationManager:
        return ObservationManager(self.api_client)


def test_ensure_db_initialized_uses_explicit_db_path(tmp_path, monkeypatch):
    monkeypatch.delenv(DB_ENV_VAR, raising=False)
    db_path = tmp_path / "explicit.db"

    manager = _NoopUpdateManager(dataset_id="TEST", source="TEST", db_path=str(db_path))

    assert LOCAL_DATABASE.database == str(db_path)
    assert db_path.exists()
    manager.database.close()


def test_ensure_db_initialized_uses_env_var(tmp_path, monkeypatch):
    db_path = tmp_path / "env.db"
    monkeypatch.setenv(DB_ENV_VAR, str(db_path))

    manager = _NoopUpdateManager(dataset_id="TEST", source="TEST")

    assert LOCAL_DATABASE.database == str(db_path)
    assert db_path.exists()
    manager.database.close()


def test_ensure_db_initialized_arg_wins_over_env(tmp_path, monkeypatch):
    env_db = tmp_path / "env.db"
    arg_db = tmp_path / "arg.db"
    monkeypatch.setenv(DB_ENV_VAR, str(env_db))

    manager = _NoopUpdateManager(dataset_id="TEST", source="TEST", db_path=str(arg_db))

    assert LOCAL_DATABASE.database == str(arg_db)
    assert arg_db.exists()
    assert not env_db.exists()
    manager.database.close()
