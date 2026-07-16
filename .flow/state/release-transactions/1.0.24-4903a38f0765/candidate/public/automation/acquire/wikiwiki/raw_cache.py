#!/usr/bin/env python3
from __future__ import annotations

"""Standalone compatibility helpers for the project's raw HTTP cache layout.

The external crawler intentionally does not import project runtime modules, but
its captured pages are written in the same deterministic layout consumed by
``util.http_cache``.  This keeps acquisition and parsing on one raw evidence
path without coupling the external tool to the core implementation.
"""

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

META_INDEX_FILE = "_meta.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def url_to_cache_path(raw_root: Path, url: str) -> Path:
    """Match ``util.http_cache.storage.url_to_path`` exactly."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"unsupported cache URL: {url}")
    path = parsed.path
    if not path or path.endswith("/"):
        path += "index.html"
    else:
        basename = os.path.basename(path)
        if "." not in basename:
            path += ".html"
    target = raw_root / parsed.netloc / path.lstrip("/")
    resolved_root = raw_root.resolve()
    resolved_target = target.resolve()
    if resolved_target != resolved_root and resolved_root not in resolved_target.parents:
        raise ValueError(f"cache URL escapes raw root: {url}")
    return target


def cache_key(raw_root: Path, path: Path) -> str:
    return path.resolve().relative_to(raw_root.resolve()).as_posix()


def read_meta_index(raw_root: Path) -> dict[str, Any]:
    path = raw_root / META_INDEX_FILE
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, prefix=path.name + "."
    ) as handle:
        handle.write(encoded)
        temp = Path(handle.name)
    os.replace(temp, path)


def _epoch_seconds(value: str | None) -> int:
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        except ValueError:
            pass
    return int(datetime.now(timezone.utc).timestamp())


def register_capture_meta(
    raw_root: Path,
    *,
    url: str,
    target_path: Path,
    fetched_at: str | None,
    http_code: int = 200,
    content_sha256: str | None = None,
    acquisition_source: str = "external-browser-session-crawl",
    capture_metadata: dict[str, Any] | None = None,
) -> None:
    digest = content_sha256 or sha256_file(target_path)
    timestamp = _epoch_seconds(fetched_at)
    index = read_meta_index(raw_root)
    entry = {
        "url": url,
        "etag": None,
        "last_modified": None,
        "fetched_at": timestamp,
        "validated_at": timestamp,
        "status_code": int(http_code),
        "fetch_status": "fresh",
        "used_cache_fallback": False,
        "content_sha256": digest,
        "acquisition_source": acquisition_source,
    }
    if capture_metadata:
        entry.update(capture_metadata)
    index[cache_key(raw_root, target_path)] = entry
    write_json_atomic(raw_root / META_INDEX_FILE, index)


def install_capture(
    source_path: Path,
    *,
    raw_root: Path,
    url: str,
    fetched_at: str | None,
    http_code: int = 200,
    expected_sha256: str | None = None,
    overwrite: bool = False,
    remove_source: bool = False,
    capture_metadata: dict[str, Any] | None = None,
) -> tuple[Path, str, str]:
    """Install one captured HTML file atomically.

    Returns ``(target_path, status, sha256)`` where status is ``installed``,
    ``replaced`` or ``already-present``.
    """

    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    source_digest = sha256_file(source_path)
    if expected_sha256 and expected_sha256 != source_digest:
        raise ValueError(
            f"source sha256 mismatch: {source_path} expected={expected_sha256} actual={source_digest}"
        )

    target_path = url_to_cache_path(raw_root, url)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    status = "installed"
    if target_path.is_file():
        target_digest = sha256_file(target_path)
        if target_digest == source_digest:
            status = "already-present"
        elif not overwrite:
            raise FileExistsError(
                f"raw cache conflict: {target_path} existing={target_digest} incoming={source_digest}"
            )
        else:
            status = "replaced"

    if status != "already-present":
        with tempfile.NamedTemporaryFile(
            "wb", dir=target_path.parent, delete=False, prefix=target_path.name + "."
        ) as handle:
            temp_path = Path(handle.name)
            with source_path.open("rb") as source:
                shutil.copyfileobj(source, handle)
        try:
            copied_digest = sha256_file(temp_path)
            if copied_digest != source_digest:
                raise OSError(
                    f"copied sha256 mismatch: {temp_path} expected={source_digest} actual={copied_digest}"
                )
            os.replace(temp_path, target_path)
        finally:
            temp_path.unlink(missing_ok=True)

    register_capture_meta(
        raw_root,
        url=url,
        target_path=target_path,
        fetched_at=fetched_at,
        http_code=http_code,
        content_sha256=source_digest,
        capture_metadata=capture_metadata,
    )
    if remove_source and not source_path.samefile(target_path):
        source_path.unlink()
    return target_path, status, source_digest
