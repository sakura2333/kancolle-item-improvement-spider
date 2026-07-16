from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from json import JSONDecodeError
from urllib.parse import urlparse

from util.http_cache import audit, settings
from util.logger import simple_logger

_META_LOCK = threading.RLock()


def url_to_path(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc
    path = parsed.path
    if not path or path.endswith("/"):
        path += "index.html"
    else:
        basename = os.path.basename(path)
        if "." not in basename:
            path += ".html"
    return os.path.join(settings.BASE_DIR, domain, path.lstrip("/"))


def meta_index_path() -> str:
    return os.path.join(settings.BASE_DIR, settings.META_INDEX_FILE)


def cache_key(path: str) -> str:
    return os.path.relpath(path, settings.BASE_DIR)


def _load_meta_index_unlocked() -> dict:
    path = meta_index_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
            return payload if isinstance(payload, dict) else {}
    except JSONDecodeError as exc:
        broken_path = f"{path}.broken.{int(time.time())}"
        os.replace(path, broken_path)
        simple_logger.error(
            f"[CACHE META BROKEN] moved {cache_key(path)} -> {cache_key(broken_path)}: {exc}"
        )
        return {}


def load_meta_index() -> dict:
    with _META_LOCK:
        return _load_meta_index_unlocked()


def _save_meta_index_unlocked(meta_index: dict) -> None:
    os.makedirs(settings.BASE_DIR, exist_ok=True)
    path = meta_index_path()
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as stream:
        json.dump(meta_index, stream, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def save_meta_index(meta_index: dict) -> None:
    with _META_LOCK:
        _save_meta_index_unlocked(meta_index)


def load_meta(path: str) -> dict:
    with _META_LOCK:
        return dict(_load_meta_index_unlocked().get(cache_key(path), {}))


def file_sha256(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_meta(path: str, url: str, response, old_meta: dict | None = None) -> None:
    old_meta = old_meta or {}
    now = int(time.time())
    with _META_LOCK:
        meta_index = _load_meta_index_unlocked()
        meta_index[cache_key(path)] = {
            "url": url,
            "etag": response.headers.get("ETag") or old_meta.get("etag"),
            "last_modified": response.headers.get("Last-Modified") or old_meta.get("last_modified"),
            "fetched_at": now,
            "validated_at": now,
            "status_code": response.status_code,
            "fetch_status": "fresh",
            "used_cache_fallback": False,
            "content_sha256": file_sha256(path) or old_meta.get("content_sha256"),
        }
        _save_meta_index_unlocked(meta_index)
    audit.mark_validated(url)


def save_failure_meta(path: str, url: str, error: Exception) -> None:
    now = int(time.time())
    with _META_LOCK:
        meta_index = _load_meta_index_unlocked()
        key = cache_key(path)
        old_meta = dict(meta_index.get(key, {}))
        meta_index[key] = {
            **old_meta,
            "url": url,
            "last_attempt_at": now,
            "fetch_status": "stale" if os.path.exists(path) else "failed",
            "used_cache_fallback": bool(os.path.exists(path)),
            "last_error": f"{type(error).__name__}: {error}",
        }
        _save_meta_index_unlocked(meta_index)


def get_fetch_meta(url: str) -> dict:
    path = url_to_path(url)
    return {
        **load_meta(path),
        "cache_path": cache_key(path),
        "validated_in_run": audit.was_validated_in_run(url),
    }


def read_text_cache(path: str) -> str:
    with open(path, "r", encoding="utf-8") as stream:
        return stream.read()


def is_local_cache_fresh(meta: dict, expire_seconds: int = settings.LOCAL_CACHE_TTL_SECONDS) -> bool:
    fetched_at = meta.get("fetched_at")
    return fetched_at is not None and time.time() - fetched_at < expire_seconds


def require_cached_file(path: str, source: str) -> None:
    if not os.path.exists(path):
        raise FileNotFoundError(f"[CACHE ONLY] cache miss: {source} -> {cache_key(path)}")
