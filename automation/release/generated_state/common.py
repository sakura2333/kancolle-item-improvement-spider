from __future__ import annotations

import fnmatch
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

_COMMIT_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

class GeneratedStateError(RuntimeError):
    pass

def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _normalize_state_relative(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise GeneratedStateError(f"{field} must be a string")
    text = value.strip().replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise GeneratedStateError(f"unsafe {field}: {value!r}")
    return path.as_posix()

def _safe_state_path(root: Path, relative: str) -> Path:
    normalized = _normalize_state_relative(relative, field="generated-state path")
    path = (root / normalized).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise GeneratedStateError(f"generated-state path escapes root: {relative!r}") from exc
    return path

def _ensure_regular_tree(path: Path) -> None:
    if path.is_symlink():
        raise GeneratedStateError(f"generated-state does not allow symlinks: {path}")
    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_symlink():
                raise GeneratedStateError(f"generated-state does not allow symlinks: {child}")

def _is_excluded(relative: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(relative, pattern) for pattern in patterns)

def _iter_files(root: Path, relative_roots: Iterable[str]) -> Iterable[Path]:
    for relative in relative_roots:
        path = _safe_state_path(root, relative)
        if not path.exists():
            raise GeneratedStateError(f"generated-state path is missing: {relative}")
        _ensure_regular_tree(path)
        if path.is_file():
            yield path
            continue
        yield from (child for child in sorted(path.rglob("*")) if child.is_file())

def _file_record(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }

def _read_project_version(project_root: Path) -> str:
    value = (project_root / "VERSION").read_text(encoding="utf-8").strip()
    if not value:
        raise GeneratedStateError("project VERSION is empty")
    return value

def _validate_commit(value: str) -> str:
    commit = value.strip()
    if not _COMMIT_RE.fullmatch(commit):
        raise GeneratedStateError(
            "base commit must be a full 40- or 64-character hexadecimal Git object id"
        )
    return commit.lower()

