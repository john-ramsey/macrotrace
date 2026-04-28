from pathlib import Path

import pytest

from macrotrace._paths import (
    CACHE_ENV_VAR,
    DB_ENV_VAR,
    DEFAULT_CACHE_NAME,
    DEFAULT_DB_NAME,
    resolve_cache_path,
    resolve_db_path,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv(DB_ENV_VAR, raising=False)
    monkeypatch.delenv(CACHE_ENV_VAR, raising=False)


def test_resolve_db_path_uses_arg_first(monkeypatch):
    monkeypatch.setenv(DB_ENV_VAR, "/from/env.db")
    assert resolve_db_path("/from/arg.db") == "/from/arg.db"


def test_resolve_db_path_falls_back_to_env(monkeypatch):
    monkeypatch.setenv(DB_ENV_VAR, "/from/env.db")
    assert resolve_db_path() == "/from/env.db"


def test_resolve_db_path_default():
    assert resolve_db_path() == DEFAULT_DB_NAME


def test_resolve_cache_path_uses_arg_first(monkeypatch):
    monkeypatch.setenv(CACHE_ENV_VAR, "/from/env.sqlite")
    monkeypatch.setenv(DB_ENV_VAR, "/from/env.db")
    assert resolve_cache_path("/from/arg.sqlite") == "/from/arg.sqlite"


def test_resolve_cache_path_uses_env(monkeypatch):
    monkeypatch.setenv(CACHE_ENV_VAR, "/from/env.sqlite")
    assert resolve_cache_path() == "/from/env.sqlite"


def test_resolve_cache_path_defaults_beside_db(monkeypatch, tmp_path):
    db_path = tmp_path / "lab.db"
    monkeypatch.setenv(DB_ENV_VAR, str(db_path))
    expected = tmp_path.resolve() / DEFAULT_CACHE_NAME
    assert resolve_cache_path() == str(expected)


def test_resolve_cache_path_default_when_nothing_set():
    assert resolve_cache_path() == DEFAULT_CACHE_NAME


def test_resolve_cache_path_arg_wins_over_db_env(monkeypatch, tmp_path):
    monkeypatch.setenv(DB_ENV_VAR, str(tmp_path / "lab.db"))
    assert resolve_cache_path("/explicit.sqlite") == "/explicit.sqlite"
