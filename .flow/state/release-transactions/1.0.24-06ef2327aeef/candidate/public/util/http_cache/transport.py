from __future__ import annotations

import random
import time

import requests

from configs.config import headers
from util.http_cache import settings
from util.http_cache.storage import cache_key
from util.logger import simple_logger


def build_conditional_headers(old_meta: dict) -> dict:
    request_headers = dict(headers)
    etag = old_meta.get("etag")
    last_modified = old_meta.get("last_modified")
    if etag:
        request_headers["If-None-Match"] = etag
    if last_modified:
        request_headers["If-Modified-Since"] = last_modified
    return request_headers


def retry_delay_seconds(attempt: int, response=None) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), settings.NETWORK_BACKOFF_CAP_SECONDS)
            except (TypeError, ValueError):
                pass
    exponential = min(
        settings.NETWORK_BACKOFF_BASE_SECONDS * (2 ** max(attempt - 1, 0)),
        settings.NETWORK_BACKOFF_CAP_SECONDS,
    )
    return exponential + random.uniform(0.0, settings.NETWORK_BACKOFF_JITTER_SECONDS)


def request_with_cache_headers(
    url: str,
    old_meta: dict,
    timeout: int,
    max_attempts: int = settings.NETWORK_MAX_ATTEMPTS,
):
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    request_headers = build_conditional_headers(old_meta)
    last_error = None
    for attempt in range(1, max_attempts + 1):
        response = None
        try:
            response = requests.get(url, headers=request_headers, timeout=timeout)
            if response.status_code not in settings.RETRYABLE_STATUS_CODES:
                return response
            last_error = requests.HTTPError(f"HTTP {response.status_code}", response=response)
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.SSLError) as error:
            last_error = error
        if attempt >= max_attempts:
            if response is not None:
                return response
            assert last_error is not None
            raise last_error
        delay = retry_delay_seconds(attempt, response=response)
        simple_logger.warning(
            f"[FETCH RETRY] {url} attempt={attempt}/{max_attempts} "
            f"delay={delay:.2f}s reason={type(last_error).__name__}: {last_error}"
        )
        if response is not None:
            response.close()
        time.sleep(delay)
    raise AssertionError("unreachable")


def log_cache_meta_updated(url: str, path: str, status_code: int) -> None:
    simple_logger.info(f"[CACHE META UPDATED] {url} -> {cache_key(path)} ({status_code})")


def log_cache_updated(url: str, path: str, status_code: int) -> None:
    simple_logger.info(f"[CACHE UPDATED] {url} -> {cache_key(path)} ({status_code})")
