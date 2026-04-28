"""Path resolution for macrotrace's SQLite files.

Resolution order for both files: explicit argument, then environment
variable, then default in the current working directory. If
``MACROTRACE_DB`` is set but ``MACROTRACE_CACHE`` is not, the cache
defaults to sitting next to the database file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

DB_ENV_VAR = "MACROTRACE_DB"
CACHE_ENV_VAR = "MACROTRACE_CACHE"

DEFAULT_DB_NAME = "MacroTrace.db"
DEFAULT_CACHE_NAME = "MacroTraceRequestCache.sqlite"


def resolve_db_path(arg: Optional[str] = None) -> str:
    if arg is not None:
        return arg
    return os.environ.get(DB_ENV_VAR) or DEFAULT_DB_NAME


def resolve_cache_path(arg: Optional[str] = None) -> str:
    if arg is not None:
        return arg
    env_value = os.environ.get(CACHE_ENV_VAR)
    if env_value:
        return env_value
    db_env = os.environ.get(DB_ENV_VAR)
    if db_env:
        return str(Path(db_env).resolve().parent / DEFAULT_CACHE_NAME)
    return DEFAULT_CACHE_NAME
