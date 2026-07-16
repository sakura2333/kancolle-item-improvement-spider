from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any


class MainContentError(RuntimeError):
    pass


def _safe_pattern(value: str) -> str:
    text = value.replace("\\", "/").strip()
    base = text[:-3] if text.endswith("/**") else text
    pure = PurePosixPath(base)
    if not text or pure.is_absolute() or ".." in pure.parts or ".git" in pure.parts:
        raise MainContentError(f"unsafe main-content path: {value!r}")
    return text


def load_main_content(root: Path | None = None) -> dict[str, Any]:
    project_root = (root or Path(__file__).resolve().parents[2]).resolve()
    path = project_root / "release/main-content.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MainContentError(f"cannot load release/main-content.json: {exc}") from exc
    if payload.get("schemaVersion") != 1:
        raise MainContentError("unsupported main-content schema")
    if payload.get("projectId") != "kancolle-item-improvement-spider":
        raise MainContentError("main-content project identity mismatch")
    categories = payload.get("categories")
    if not isinstance(categories, dict) or not categories:
        raise MainContentError("main-content categories are missing")
    include: list[str] = []
    for name, values in categories.items():
        if not isinstance(name, str) or not isinstance(values, list) or not values:
            raise MainContentError(f"invalid main-content category: {name!r}")
        include.extend(_safe_pattern(str(value)) for value in values)
    for field in ("required", "internalOnly", "forbidden", "generated", "generatedState"):
        values = payload.get(field)
        if not isinstance(values, list):
            raise MainContentError(f"main-content {field} must be an array")
        payload[field] = [_safe_pattern(str(value)) for value in values]
    if len(include) != len(set(include)):
        raise MainContentError("main-content include patterns contain duplicates")
    internal = set(payload["internalOnly"])
    overlap = sorted(set(include) & internal)
    if overlap:
        raise MainContentError(f"main-content includes internal patterns: {overlap}")
    result = dict(payload)
    result["include"] = include
    return result
