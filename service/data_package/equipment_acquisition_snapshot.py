from __future__ import annotations

"""Refresh or reuse the public WikiWiki equipment-acquisition snapshot.

A maintainer checkout may contain the local Raw Cache and can rebuild the
snapshot from original HTML evidence.  A clean public ``main`` checkout does
not publish Raw Cache, so the scheduled public pipeline must instead validate
and reuse the already published acquisition snapshot.

The fallback is intentionally narrow: it is used only when ``_meta.json`` is
absent.  If local raw evidence exists but is corrupt, parsing still fails and
is never hidden by an older snapshot.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from service.data_package.equipment_acquisition import SOURCE_ID
from service.data_package.equipment_acquisition_raw_parse import run_offline_parse
from util.logger import simple_logger


_REQUIRED_SNAPSHOT_FILES = (
    "catalog.json",
    "acquisition-records.nedb",
    "dataset-issues.nedb",
    "reference-issues.nedb",
    "unclassified-evidence.nedb",
    "dataset-metadata.json",
)


class AcquisitionSnapshotError(ValueError):
    pass


@dataclass(frozen=True)
class AcquisitionSnapshot:
    records: list[dict[str, Any]]
    metadata: dict[str, Any]
    input_mode: str


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcquisitionSnapshotError(
            f"equipment acquisition snapshot is unreadable: {path}: {exc}"
        ) from exc




def _read_json_lines_strict(path: Path) -> list[Any]:
    values: list[Any] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, 1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    values.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise AcquisitionSnapshotError(
                        f"equipment acquisition NDJSON is invalid: "
                        f"{path}:{line_number}: {exc}"
                    ) from exc
    except OSError as exc:
        raise AcquisitionSnapshotError(
            f"equipment acquisition NDJSON is unreadable: {path}: {exc}"
        ) from exc
    return values

def _require_count(metadata: dict[str, Any], key: str, actual: int) -> None:
    try:
        expected = int(metadata.get(key))
    except (TypeError, ValueError) as exc:
        raise AcquisitionSnapshotError(
            f"equipment acquisition metadata has invalid {key!r}"
        ) from exc
    if expected != actual:
        raise AcquisitionSnapshotError(
            f"equipment acquisition snapshot count mismatch: "
            f"{key}={expected}, actual={actual}"
        )


def validate_acquisition_snapshot(output_dir: Path) -> AcquisitionSnapshot:
    output_dir = output_dir.resolve()
    missing = [
        name for name in _REQUIRED_SNAPSHOT_FILES
        if not (output_dir / name).is_file()
    ]
    if missing:
        raise AcquisitionSnapshotError(
            "equipment acquisition public snapshot is incomplete; "
            f"missing={missing}; outputDir={output_dir}"
        )

    metadata_payload = _read_json(output_dir / "dataset-metadata.json")
    if not isinstance(metadata_payload, dict):
        raise AcquisitionSnapshotError(
            "equipment acquisition metadata must be a JSON object"
        )
    metadata: dict[str, Any] = metadata_payload
    if metadata.get("schemaVersion") != 1:
        raise AcquisitionSnapshotError(
            "unsupported equipment acquisition metadata schema: "
            f"{metadata.get('schemaVersion')!r}"
        )
    if metadata.get("source") != SOURCE_ID:
        raise AcquisitionSnapshotError(
            "equipment acquisition metadata source mismatch: "
            f"{metadata.get('source')!r}"
        )

    catalog_payload = _read_json(output_dir / "catalog.json")
    if not isinstance(catalog_payload, list):
        raise AcquisitionSnapshotError(
            "equipment acquisition catalog must be a JSON array"
        )

    records = _read_json_lines_strict(output_dir / "acquisition-records.nedb")
    dataset_issues = _read_json_lines_strict(output_dir / "dataset-issues.nedb")
    reference_issues = _read_json_lines_strict(output_dir / "reference-issues.nedb")
    unclassified = _read_json_lines_strict(output_dir / "unclassified-evidence.nedb")

    _require_count(metadata, "catalogEntryCount", len(catalog_payload))
    _require_count(metadata, "recordCount", len(records))
    _require_count(
        metadata,
        "acceptedRecordCount",
        sum(1 for record in records if record.get("accepted") is True),
    )
    _require_count(metadata, "issueCount", len(dataset_issues))
    _require_count(metadata, "referenceIssueCount", len(reference_issues))
    _require_count(metadata, "unclassifiedEvidenceCount", len(unclassified))

    seen_ids: set[int] = set()
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict):
            raise AcquisitionSnapshotError(
                f"equipment acquisition record {index} must be an object"
            )
        try:
            equipment_id = int(record.get("equipmentId"))
        except (TypeError, ValueError) as exc:
            raise AcquisitionSnapshotError(
                f"equipment acquisition record {index} has invalid equipmentId"
            ) from exc
        if equipment_id <= 0 or equipment_id in seen_ids:
            raise AcquisitionSnapshotError(
                "equipment acquisition records require unique positive equipmentId; "
                f"found={equipment_id}"
            )
        seen_ids.add(equipment_id)
        if record.get("source") != SOURCE_ID:
            raise AcquisitionSnapshotError(
                f"equipment acquisition record {equipment_id} has wrong source"
            )
        if record.get("schemaVersion") != 3:
            raise AcquisitionSnapshotError(
                f"equipment acquisition record {equipment_id} has unsupported schema"
            )
        if record.get("accepted") is not True:
            raise AcquisitionSnapshotError(
                f"equipment acquisition record {equipment_id} is not accepted"
            )

    for stop_name in ("operator-stop.json", "operator-stops.nedb"):
        stop_path = output_dir / stop_name
        if stop_path.is_file() and stop_path.stat().st_size > 0:
            raise AcquisitionSnapshotError(
                "equipment acquisition snapshot still contains an operator stop: "
                f"{stop_path}"
            )

    return AcquisitionSnapshot(
        records=records,
        metadata=metadata,
        input_mode="validated-public-snapshot",
    )


def refresh_or_reuse_acquisition_snapshot(
    *,
    raw_root: Path,
    output_dir: Path,
    quest_catalog_text: str | None,
    allow_incomplete: bool,
) -> AcquisitionSnapshot:
    raw_root = raw_root.resolve()
    output_dir = output_dir.resolve()
    raw_metadata = raw_root / "_meta.json"

    if raw_metadata.is_file():
        run_offline_parse(
            raw_root=raw_root,
            output_dir=output_dir,
            quest_catalog_text=quest_catalog_text,
            allow_incomplete=allow_incomplete,
        )
        snapshot = validate_acquisition_snapshot(output_dir)
        simple_logger.info(
            "[equipment acquisition] rebuilt from local raw cache and validated; "
            f"records={len(snapshot.records)}"
        )
        return AcquisitionSnapshot(
            records=snapshot.records,
            metadata=snapshot.metadata,
            input_mode="local-raw-cache",
        )

    snapshot = validate_acquisition_snapshot(output_dir)
    simple_logger.info(
        "[equipment acquisition] raw cache is not published; reusing validated "
        "public acquisition snapshot; "
        f"records={len(snapshot.records)} generatedAt={snapshot.metadata.get('generatedAt')}"
    )
    return snapshot
