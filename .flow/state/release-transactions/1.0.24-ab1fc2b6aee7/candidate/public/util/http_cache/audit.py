from __future__ import annotations

import threading

_VALIDATED_URLS: set[str] = set()
_VALIDATED_URLS_LOCK = threading.Lock()
_COMPLETED_COLLECTIONS: set[str] = set()
_COMPLETED_COLLECTIONS_LOCK = threading.Lock()


def mark_validated(url: str) -> None:
    with _VALIDATED_URLS_LOCK:
        _VALIDATED_URLS.add(url)


def was_validated_in_run(url: str) -> bool:
    with _VALIDATED_URLS_LOCK:
        return url in _VALIDATED_URLS


def reset_fetch_audit() -> None:
    with _VALIDATED_URLS_LOCK:
        _VALIDATED_URLS.clear()
    with _COMPLETED_COLLECTIONS_LOCK:
        _COMPLETED_COLLECTIONS.clear()


def mark_collection_completed(source: str) -> None:
    with _COMPLETED_COLLECTIONS_LOCK:
        _COMPLETED_COLLECTIONS.add(source)


def collection_completed_in_run(source: str) -> bool:
    with _COMPLETED_COLLECTIONS_LOCK:
        return source in _COMPLETED_COLLECTIONS
