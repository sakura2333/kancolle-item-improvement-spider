from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from automation.release.generated_state.common import (
    _SHA256_RE,
    GeneratedStateError,
    _ensure_regular_tree,
    _iter_files,
    _normalize_state_relative,
    _safe_state_path,
    _sha256,
    _validate_commit,
)
from automation.release.generated_state.config import GeneratedStateConfig, load_generated_state_config

def load_generated_state_manifest(
    state_root: Path,
    config: GeneratedStateConfig | None = None,
) -> dict[str, Any]:
    root = state_root.expanduser().resolve()
    state_config = config or load_generated_state_config()
    path = _safe_state_path(root, state_config.manifest_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GeneratedStateError(f"generated-state manifest is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GeneratedStateError(f"invalid generated-state manifest: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise GeneratedStateError("unsupported generated-state manifest schema")
    if payload.get("stateId") != state_config.state_id:
        raise GeneratedStateError(
            f"generated-state id mismatch: {payload.get('stateId')!r}"
        )
    if payload.get("role") != "generated-state":
        raise GeneratedStateError("generated-state manifest has an invalid role")
    base_revision = payload.get("baseRevision")
    if not isinstance(base_revision, dict) or base_revision.get("type") != "git":
        raise GeneratedStateError("generated-state manifest has no Git base revision")
    _validate_commit(str(base_revision.get("commit", "")))
    generator = payload.get("generator")
    if not isinstance(generator, dict) or generator.get("contractVersion") != 1:
        raise GeneratedStateError("unsupported generated-state generator contract")
    if not str(payload.get("buildId", "")).strip():
        raise GeneratedStateError("generated-state manifest has no buildId")
    return payload

def _validated_record(record: object, *, field: str) -> tuple[str, str, int]:
    if not isinstance(record, dict):
        raise GeneratedStateError(f"{field} record must be an object")
    relative = _normalize_state_relative(record.get("path"), field=f"{field}.path")
    digest = str(record.get("sha256", ""))
    if not _SHA256_RE.fullmatch(digest):
        raise GeneratedStateError(f"invalid sha256 for {relative}")
    size = record.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise GeneratedStateError(f"invalid size for {relative}")
    return relative, digest, size

def verify_generated_state(
    state_root: Path,
    config: GeneratedStateConfig | None = None,
) -> dict[str, Any]:
    root = state_root.expanduser().resolve()
    state_config = config or load_generated_state_config()
    manifest = load_generated_state_manifest(root, state_config)
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise GeneratedStateError("generated-state manifest has no outputs")

    expected: dict[str, tuple[str, int]] = {}
    for record in outputs:
        relative, digest, size = _validated_record(record, field="outputs")
        relative = state_config.validate_relative_path(relative, require_exported=True)
        if relative in expected:
            raise GeneratedStateError(f"duplicate generated-state output: {relative}")
        expected[relative] = (digest, size)

    actual_paths = {
        path.relative_to(root).as_posix()
        for path in _iter_files(root, state_config.export_paths)
    }
    if actual_paths != set(expected):
        missing = sorted(set(expected) - actual_paths)
        extra = sorted(actual_paths - set(expected))
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing[:20]))
        if extra:
            details.append("extra: " + ", ".join(extra[:20]))
        raise GeneratedStateError("generated-state file set mismatch; " + "; ".join(details))

    verified_bytes = 0
    for relative, (expected_hash, expected_size) in expected.items():
        path = _safe_state_path(root, relative)
        _ensure_regular_tree(path)
        actual_size = path.stat().st_size
        actual_hash = _sha256(path)
        if actual_size != expected_size:
            raise GeneratedStateError(f"size mismatch: {relative}")
        if actual_hash != expected_hash:
            raise GeneratedStateError(f"sha256 mismatch: {relative}")
        verified_bytes += actual_size

    seen_reports: set[str] = set()
    reports = manifest.get("reports", [])
    if not isinstance(reports, list):
        raise GeneratedStateError("generated-state reports must be an array")
    for report in reports:
        relative, expected_hash, expected_size = _validated_record(report, field="reports")
        if not relative.startswith(".generated-state/reports/"):
            raise GeneratedStateError(f"invalid report path: {relative}")
        if relative in seen_reports:
            raise GeneratedStateError(f"duplicate generated-state report: {relative}")
        seen_reports.add(relative)
        path = _safe_state_path(root, relative)
        _ensure_regular_tree(path)
        if not path.is_file():
            raise GeneratedStateError(f"generated-state report is missing: {relative}")
        if path.stat().st_size != expected_size or _sha256(path) != expected_hash:
            raise GeneratedStateError(f"report integrity mismatch: {relative}")

    return {
        "schemaVersion": 1,
        "stateId": manifest["stateId"],
        "buildId": manifest.get("buildId"),
        "baseCommit": manifest.get("baseRevision", {}).get("commit"),
        "outputCount": len(expected),
        "verifiedBytes": verified_bytes,
        "manifest": str((root / state_config.manifest_path).resolve()),
    }

