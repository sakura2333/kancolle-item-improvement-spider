from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any


class PublicContentError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_pattern(value: str) -> str:
    text = value.replace("\\", "/").strip()
    base = text[:-3] if text.endswith("/**") else text
    pure = PurePosixPath(base)
    if not text or pure.is_absolute() or ".." in pure.parts or ".git" in pure.parts:
        raise PublicContentError(f"unsafe public-content path: {value!r}")
    return text


def _load_exceptions(project_root: Path, relative: str) -> tuple[dict[str, Any], str]:
    path = project_root / _safe_pattern(relative)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublicContentError(f"cannot load public exceptions: {exc}") from exc
    if payload.get("schemaVersion") != 1:
        raise PublicContentError("unsupported public-exceptions schema")
    if payload.get("projectId") != "kancolle-item-improvement-spider":
        raise PublicContentError("public-exceptions project identity mismatch")
    if payload.get("policy") != "deny-by-default-explicit-public-exceptions":
        raise PublicContentError("public-exceptions policy mismatch")
    entries = payload.get("exceptions")
    if not isinstance(entries, list):
        raise PublicContentError("public-exceptions entries must be an array")
    ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise PublicContentError("public-exceptions entry must be an object")
        identifier = str(entry.get("id") or "")
        if not identifier or identifier in ids:
            raise PublicContentError(f"invalid or duplicate public exception id: {identifier!r}")
        ids.add(identifier)
        for field in ("category", "reason", "owner", "review"):
            if not str(entry.get(field) or "").strip():
                raise PublicContentError(f"public exception {identifier} missing {field}")
        expires = entry.get("expires")
        if expires is not None:
            try:
                if date.fromisoformat(str(expires)) < date.today():
                    raise PublicContentError(f"public exception expired: {identifier}")
            except ValueError as exc:
                raise PublicContentError(f"invalid public exception expiry: {identifier}") from exc
        matches = entry.get("matches", [])
        review_files = entry.get("reviewFiles", [])
        if not matches and not review_files:
            raise PublicContentError(f"public exception {identifier} has no matches or reviewFiles")
        if not isinstance(matches, list) or not isinstance(review_files, list):
            raise PublicContentError(f"public exception {identifier} paths must be arrays")
        for match in matches:
            if not isinstance(match, dict):
                raise PublicContentError(f"public exception {identifier} match must be an object")
            _safe_pattern(str(match.get("path") or ""))
            if not str(match.get("literal") or ""):
                raise PublicContentError(f"public exception {identifier} has empty literal")
            if int(match.get("expectedOccurrences", 0)) < 1:
                raise PublicContentError(f"public exception {identifier} has invalid expectedOccurrences")
        for value in review_files:
            _safe_pattern(str(value))
        forbidden = entry.get("forbiddenContent", [])
        if not isinstance(forbidden, list) or any(not str(value) for value in forbidden):
            raise PublicContentError(f"public exception {identifier} forbiddenContent must be strings")
    return payload, _sha256(path)


def load_public_content(root: Path | None = None) -> dict[str, Any]:
    project_root = (root or Path(__file__).resolve().parents[2]).resolve()
    path = project_root / "release/public-content.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublicContentError(f"cannot load release/public-content.json: {exc}") from exc
    if payload.get("schemaVersion") != 3:
        raise PublicContentError("unsupported public-content schema")
    if payload.get("projectId") != "kancolle-item-improvement-spider":
        raise PublicContentError("public-content project identity mismatch")
    if payload.get("policy") != "whitelist-public-snapshot":
        raise PublicContentError("public-content policy must be whitelist-public-snapshot")
    channels = payload.get("channels")
    if channels != ["beta", "stable"]:
        raise PublicContentError("public-content channels must be beta and stable")
    categories = payload.get("categories")
    if not isinstance(categories, dict) or not categories:
        raise PublicContentError("public-content categories are missing")
    include: list[str] = []
    for name, values in categories.items():
        if not isinstance(name, str) or not isinstance(values, list) or not values:
            raise PublicContentError(f"invalid public-content category: {name!r}")
        include.extend(_safe_pattern(str(value)) for value in values)
    for field in ("required", "internalOnly", "forbidden", "generated", "generatedState"):
        values = payload.get(field)
        if not isinstance(values, list):
            raise PublicContentError(f"public-content {field} must be an array")
        payload[field] = [_safe_pattern(str(value)) for value in values]
    for field in ("publicForbiddenText", "publicReviewText", "publicGitignore"):
        values = payload.get(field)
        if not isinstance(values, list) or any(not str(value) for value in values):
            raise PublicContentError(f"public-content {field} must be a non-empty string array")
        payload[field] = [str(value) for value in values]
    if len(include) != len(set(include)):
        raise PublicContentError("public-content include patterns contain duplicates")
    internal = set(payload["internalOnly"])
    overlap = sorted(set(include) & internal)
    if overlap:
        raise PublicContentError(f"public-content includes internal patterns: {overlap}")
    exception_path = str(payload.get("exceptionsFile") or "")
    exceptions, exception_hash = _load_exceptions(project_root, exception_path)
    result = dict(payload)
    result["include"] = include
    result["publicExceptions"] = exceptions
    result["publicExceptionsSha256"] = exception_hash
    return result
