from __future__ import annotations

"""Producer-owned semantic identities for consumer data files.

Data producers define which fields are provenance-only. Release code consumes
this normalization instead of maintaining a second list of semantic rules.
Binary assets remain byte-identical by design.
"""

from copy import deepcopy
import hashlib
import json
from typing import Any

IMPROVEMENT_LIST_RELATIVE = "improvement/list.json"
IMPROVEMENT_LIST_CONTENT_DIGEST_SCHEMA_VERSION = 1

# These fields describe build/source provenance rather than consumer business
# content. They must not allocate a new npm version by themselves.
_IMPROVEMENT_LIST_VOLATILE_METADATA = {
    "dataVersion",
    "generatedAt",
    "shipMasterVersion",
    "contentDigest",
}


class ContentDigestError(ValueError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _parse_json(raw: bytes, *, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContentDigestError(f"invalid JSON: {label}: {exc}") from exc


def improvement_list_semantic_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContentDigestError("improvement/list.json must contain an object")
    metadata = value.get("metadata")
    if not isinstance(metadata, dict):
        raise ContentDigestError("improvement/list.json metadata must contain an object")

    normalized = deepcopy(value)
    normalized_metadata = dict(normalized["metadata"])
    for key in _IMPROVEMENT_LIST_VOLATILE_METADATA:
        normalized_metadata.pop(key, None)
    normalized["metadata"] = normalized_metadata
    return normalized


def improvement_list_content_digest(value: Any) -> str:
    semantic = improvement_list_semantic_value(value)
    return hashlib.sha256(canonical_json_bytes(semantic)).hexdigest()


def stamp_improvement_list_content_digest(value: Any) -> dict[str, Any]:
    result = deepcopy(value)
    if not isinstance(result, dict) or not isinstance(result.get("metadata"), dict):
        raise ContentDigestError("improvement/list.json metadata must contain an object")
    result["metadata"]["contentDigestSchemaVersion"] = (
        IMPROVEMENT_LIST_CONTENT_DIGEST_SCHEMA_VERSION
    )
    digest = improvement_list_content_digest(result)
    result["metadata"]["contentDigest"] = f"sha256:{digest}"
    return result


def _validate_improvement_list_content_digest(value: Any) -> None:
    if not isinstance(value, dict):
        raise ContentDigestError("improvement/list.json must contain an object")
    metadata = value.get("metadata")
    if not isinstance(metadata, dict):
        raise ContentDigestError("improvement/list.json metadata must contain an object")

    declared = metadata.get("contentDigest")
    if declared is None:
        # Compatibility with already-published packages that predate the
        # producer-owned digest. They can still be normalized deterministically.
        return

    schema = metadata.get("contentDigestSchemaVersion")
    if schema != IMPROVEMENT_LIST_CONTENT_DIGEST_SCHEMA_VERSION:
        raise ContentDigestError(
            "unsupported improvement/list.json contentDigestSchemaVersion: "
            f"{schema!r}"
        )
    actual = improvement_list_content_digest(value)
    normalized = str(declared).strip().lower()
    if normalized not in {actual, f"sha256:{actual}"}:
        raise ContentDigestError(
            "improvement/list.json contentDigest mismatch: "
            f"declared={declared!r} actual=sha256:{actual}"
        )


def normalized_json_bytes(relative: str, raw: bytes) -> bytes:
    value = _parse_json(raw, label=relative)
    if relative == IMPROVEMENT_LIST_RELATIVE:
        _validate_improvement_list_content_digest(value)
        value = improvement_list_semantic_value(value)
    return canonical_json_bytes(value)


def normalized_json_lines_bytes(relative: str, raw: bytes) -> bytes:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContentDigestError(f"invalid UTF-8 JSONL: {relative}: {exc}") from exc

    lines: list[bytes] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContentDigestError(
                f"invalid JSONL: {relative}:{line_number}: {exc}"
            ) from exc
        lines.append(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    return b"\n".join(lines) + (b"\n" if lines else b"")


def normalized_data_bytes(relative: str, raw: bytes) -> bytes:
    if relative.endswith(".json"):
        return normalized_json_bytes(relative, raw)
    if relative.endswith(".nedb"):
        return normalized_json_lines_bytes(relative, raw)
    return raw
