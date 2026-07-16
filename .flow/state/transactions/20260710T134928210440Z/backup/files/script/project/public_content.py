from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any


class PublicContentError(RuntimeError):
    pass


def _safe_pattern(value: str) -> str:
    text = value.replace("\\", "/").strip()
    base = text[:-3] if text.endswith("/**") else text
    pure = PurePosixPath(base)
    if not text or pure.is_absolute() or ".." in pure.parts or ".git" in pure.parts:
        raise PublicContentError(f"unsafe public-content path: {value!r}")
    return text


def load_public_content(root: Path | None = None) -> dict[str, Any]:
    project_root = (root or Path(__file__).resolve().parents[2]).resolve()
    path = project_root / "release/public-content.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublicContentError(f"cannot load release/public-content.json: {exc}") from exc
    if payload.get("schemaVersion") != 2:
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
    if len(include) != len(set(include)):
        raise PublicContentError("public-content include patterns contain duplicates")
    internal = set(payload["internalOnly"])
    overlap = sorted(set(include) & internal)
    if overlap:
        raise PublicContentError(f"public-content includes internal patterns: {overlap}")
    result = dict(payload)
    result["include"] = include
    return result
