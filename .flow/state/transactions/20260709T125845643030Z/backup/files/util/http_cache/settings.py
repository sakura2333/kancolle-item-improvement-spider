from __future__ import annotations

import os

from configs.path import SOURCE_CACHE_DIR

BASE_DIR = SOURCE_CACHE_DIR
META_INDEX_FILE = "_meta.json"
LOCAL_CACHE_TTL_SECONDS = 22 * 60 * 60
TEXT_REQUEST_TIMEOUT_SECONDS = 10
FILE_REQUEST_TIMEOUT_SECONDS = 30
FILE_CACHE_TTL_SECONDS = 7 * 24 * 3600
IMAGE_CACHE_TTL_SECONDS = 30 * 24 * 3600
NETWORK_MAX_ATTEMPTS = 4
NETWORK_BACKOFF_BASE_SECONDS = 1.0
NETWORK_BACKOFF_CAP_SECONDS = 8.0
NETWORK_BACKOFF_JITTER_SECONDS = 0.25
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def strict_fetch_enabled() -> bool:
    return _env_enabled("DATA_PACKAGE_STRICT") or _env_enabled("FETCH_STRICT")
