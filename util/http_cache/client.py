from __future__ import annotations

import os

import requests

from configs.config import CACHE_ONLY
from util.http_cache import audit, settings, storage, transport
from util.logger import simple_logger


def fetch(url: str, force: bool = False, require_fresh: bool | None = None) -> str:
    path = storage.url_to_path(url)
    old_meta = storage.load_meta(path)
    require_fresh = settings.strict_fetch_enabled() if require_fresh is None else bool(require_fresh)
    if CACHE_ONLY:
        storage.require_cached_file(path, url)
        simple_logger.debug(f"[CACHE ONLY] {url} -> {storage.cache_key(path)}")
        return storage.read_text_cache(path)
    if not force and os.path.exists(path) and audit.was_validated_in_run(url):
        simple_logger.debug(f"[CACHE VALIDATED THIS RUN] {url} -> {storage.cache_key(path)}")
        return storage.read_text_cache(path)
    if not force and os.path.exists(path) and not require_fresh and storage.is_local_cache_fresh(old_meta):
        simple_logger.debug(f"[CACHE] {url} -> {storage.cache_key(path)}")
        return storage.read_text_cache(path)
    try:
        response = transport.request_with_cache_headers(url, old_meta, settings.TEXT_REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 304:
            storage.require_cached_file(path, url)
            storage.save_meta(path, url, response, old_meta=old_meta)
            transport.log_cache_meta_updated(url, path, response.status_code)
            return storage.read_text_cache(path)
        response.raise_for_status()
    except requests.RequestException as error:
        storage.save_failure_meta(path, url, error)
        if os.path.exists(path) and not require_fresh:
            simple_logger.error(f"[FETCH FAILED][CACHE FALLBACK] {url}: {error}")
            return storage.read_text_cache(path)
        raise RuntimeError(f"fresh fetch required for {url}: {error}") from error
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(response.text)
    storage.save_meta(path, url, response, old_meta=old_meta)
    transport.log_cache_updated(url, path, response.status_code)
    return response.text


def download_file(
    url: str,
    save_path: str,
    force: bool = False,
    expire_seconds: int = settings.FILE_CACHE_TTL_SECONDS,
    require_fresh: bool | None = None,
) -> str:
    save_path = os.path.join(settings.BASE_DIR, save_path)
    old_meta = storage.load_meta(save_path)
    require_fresh = settings.strict_fetch_enabled() if require_fresh is None else bool(require_fresh)
    if CACHE_ONLY:
        storage.require_cached_file(save_path, url)
        simple_logger.debug(f"[CACHE ONLY] {url} -> {storage.cache_key(save_path)}")
        return save_path
    if not force and os.path.exists(save_path) and audit.was_validated_in_run(url):
        simple_logger.debug(f"[CACHE VALIDATED THIS RUN] {url} -> {storage.cache_key(save_path)}")
        return save_path
    if not force and os.path.exists(save_path) and not require_fresh and storage.is_local_cache_fresh(old_meta, expire_seconds):
        simple_logger.debug(f"[CACHE] {url} -> {storage.cache_key(save_path)}")
        return save_path
    try:
        response = transport.request_with_cache_headers(url, old_meta, settings.FILE_REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 304:
            storage.require_cached_file(save_path, url)
            storage.save_meta(save_path, url, response, old_meta=old_meta)
            transport.log_cache_meta_updated(url, save_path, response.status_code)
            return save_path
        response.raise_for_status()
    except requests.RequestException as error:
        storage.save_failure_meta(save_path, url, error)
        if os.path.exists(save_path) and not require_fresh:
            simple_logger.error(f"[FETCH FAILED][CACHE FALLBACK] {url}: {error}")
            return save_path
        raise RuntimeError(f"fresh download required for {url}: {error}") from error
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "wb") as stream:
        stream.write(response.content)
    storage.save_meta(save_path, url, response, old_meta=old_meta)
    transport.log_cache_updated(url, save_path, response.status_code)
    return save_path
