from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from service.data_package.equipment_bonus import SOURCE_URL as BONUS_URL
from service.data_package.equipment_drop_from import EQUIPMENT_URL, SHIP_URL
from service.data_package.equipment_acquisition_raw_parse import DEFAULT_RAW_ROOT
from service.data_package.equipment_acquisition_snapshot import (
    refresh_or_reuse_acquisition_snapshot,
)
from service.data_package.equipment_sources import (
    build_equipment_source_records,
    write_incremental_source_bundle,
)
from service.data_package.improvement_compat import (
    IMPROVEMENT2_CONSUMER_ID,
    IMPROVEMENT2_DETAIL_SCHEMA_VERSION,
    IMPROVEMENT2_LIST_SCHEMA_VERSION,
    write_improvement2_projection,
)
from service.data_package.manifest_builder import package_version, refresh_package_manifest
from service.data_package.package_paths import (
    AKASHI_METADATA_PATH,
    AKASHI_URL,
    CACHE_IMAGE_DIR,
    IMPROVEMENT2_COMPAT_DIR,
    IMPROVEMENT_DIR,
    PACKAGE_DIR,
    SOURCE_ROOT,
    STATIC_IMAGE_DIR,
)
from service.data_package.projection import (
    _clear_regenerated as clear_regenerated,
    _copy_file as copy_file,
    _copy_icon_directory as copy_icon_directory,
    _improvement_projection_metrics as improvement_projection_metrics,
    _promote_cached_icons as promote_cached_icons,
    _required_useitem_ids as required_useitem_ids,
)
from service.data_package.source_collection import (
    _fetch_summary,
    _improvement_source_metadata as improvement_source_metadata,
    _source_status,
    collect_optional_datasets,
)
from util.json_utils import read_json_lines, write_json, write_json_lines
from util.logger import simple_logger
from util.start2.start2_item_utils import start2ItemUtils


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_data_package(strict: Optional[bool] = None) -> dict:
    strict = strict if strict is not None else os.getenv("DATA_PACKAGE_STRICT", "0").lower() in {"1", "true", "yes", "on"}
    previous_manifest = {}
    manifest_path = PACKAGE_DIR / "manifest.json"
    if manifest_path.exists():
        try:
            previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            previous_manifest = {}
    clear_regenerated()
    datasets = collect_optional_datasets(strict=strict)
    improvement_source = improvement_source_metadata(strict)

    copy_file(IMPROVEMENT_DIR / "improvement-list.json", PACKAGE_DIR / "improvement" / "list.json")
    copy_file(IMPROVEMENT_DIR / "improvement-detail.nedb", PACKAGE_DIR / "improvement" / "detail.nedb")

    compatibility_improvement_dir = IMPROVEMENT2_COMPAT_DIR / "improvement"
    copy_file(
        PACKAGE_DIR / "improvement" / "list.json",
        compatibility_improvement_dir / "list.json",
    )
    improvement2_metrics = write_improvement2_projection(
        PACKAGE_DIR / "improvement" / "detail.nedb",
        compatibility_improvement_dir / "detail.nedb",
    )

    dataset_targets = {
        "dropFrom": PACKAGE_DIR / "equipment" / "drop-from.nedb",
        "specialBonuses": PACKAGE_DIR / "equipment" / "special-bonuses.nedb",
    }
    previous_datasets = previous_manifest.get("datasets", {}) if isinstance(previous_manifest, dict) else {}
    for dataset_key, target in dataset_targets.items():
        dataset = datasets[dataset_key]
        failed = dataset["metadata"].get("status") == "failed"
        if not failed:
            write_json_lines(str(target), dataset["records"], mode="w", log=True)
            continue
        if target.exists():
            previous_key = "equipmentDropFrom" if dataset_key == "dropFrom" else "equipmentSpecialBonuses"
            previous = previous_datasets.get(previous_key, {})
            dataset["metadata"] = {
                **previous,
                "status": "stale",
                "refreshError": dataset["metadata"].get("error"),
            }
            simple_logger.warning(f"[data package] preserving previous {target.name} after refresh failure")
        else:
            write_json_lines(str(target), [], mode="w", log=True)

    acquisition_dir = SOURCE_ROOT / "wikiwiki-equipment-detail"
    acquisition_path = acquisition_dir / "acquisition-records.nedb"
    quest_catalog = datasets.get("questCatalog", {}).get("catalog")
    acquisition_snapshot = refresh_or_reuse_acquisition_snapshot(
        raw_root=DEFAULT_RAW_ROOT,
        output_dir=acquisition_dir,
        quest_catalog_text=(
            json.dumps(quest_catalog, ensure_ascii=False)
            if isinstance(quest_catalog, dict)
            else None
        ),
        allow_incomplete=not strict,
    )
    acquisition_records = acquisition_snapshot.records
    equipment_source_records, equipment_source_metadata = build_equipment_source_records(
        item_utils=start2ItemUtils.load(),
        drop_records=read_json_lines(PACKAGE_DIR / "equipment" / "drop-from.nedb"),
        improvement_path=PACKAGE_DIR / "improvement" / "detail.nedb",
        acquisition_records=acquisition_records,
    )
    equipment_source_dir = SOURCE_ROOT / "equipment-sources"
    equipment_source_incremental = write_incremental_source_bundle(
        records=equipment_source_records,
        output_path=equipment_source_dir / "equipment-sources.nedb",
        metadata_path=equipment_source_dir / "dataset-metadata.json",
        changes_path=equipment_source_dir / "changes.nedb",
        metadata=equipment_source_metadata,
        input_hashes={
            "improvementDetail": _file_sha256(PACKAGE_DIR / "improvement" / "detail.nedb"),
            "wikiwikiAcquisition": _file_sha256(acquisition_path),
            "kcwikiShip": _fetch_summary(SHIP_URL).get("contentSha256"),
            "kcwikiEquipment": _fetch_summary(EQUIPMENT_URL).get("contentSha256"),
        },
    )
    write_json_lines(
        str(PACKAGE_DIR / "equipment" / "sources.nedb"),
        equipment_source_records,
        mode="w",
        log=True,
    )

    # Promote freshly downloaded images into a stable tracked source directory,
    # then build the package exclusively from that reproducible asset set.
    promote_cached_icons()
    copy_icon_directory(STATIC_IMAGE_DIR, PACKAGE_DIR / "assets" / "useitems")

    required_icon_ids = required_useitem_ids(PACKAGE_DIR / "improvement" / "detail.nedb")
    available_icon_ids = sorted(
        int(path.stem)
        for path in (PACKAGE_DIR / "assets" / "useitems").glob("*.png")
        if path.stem.isdigit()
    )
    missing_icon_ids = sorted(set(required_icon_ids) - set(available_icon_ids))
    if strict and missing_icon_ids:
        raise ValueError(f"required use-item icons are missing: {missing_icon_ids}")

    list_document = json.loads((PACKAGE_DIR / "improvement" / "list.json").read_text(encoding="utf-8"))
    list_views = list_document.get("data", []) if isinstance(list_document, dict) else []
    list_all_count = len(list_views[0]) if isinstance(list_views, list) and list_views and isinstance(list_views[0], list) else 0
    improvement_metrics = improvement_projection_metrics(
        PACKAGE_DIR / "improvement" / "detail.nedb"
    )

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    compatibility_manifest = {
        "packageVersion": f"{package_version()}-improvement2",
        "generatedAt": generated_at,
        "consumer": IMPROVEMENT2_CONSUMER_ID,
        "datasets": {
            "improvement": {
                "schemaVersion": IMPROVEMENT2_DETAIL_SCHEMA_VERSION,
                "listSchemaVersion": IMPROVEMENT2_LIST_SCHEMA_VERSION,
                "list": "improvement/list.json",
                "detail": "improvement/detail.nedb",
                **improvement2_metrics,
            }
        },
    }
    write_json(
        str(IMPROVEMENT2_COMPAT_DIR / "manifest.json"),
        compatibility_manifest,
        mode="w",
        log=True,
    )

    manifest = {
        "packageVersion": package_version(),
        "generatedAt": generated_at,
        "datasets": {
            "improvement": {
                "schemaVersion": 4,
                "listSchemaVersion": 2,
                "list": "improvement/list.json",
                "detail": "improvement/detail.nedb",
                "listViewCount": len(list_views),
                "listAllCount": list_all_count,
                **improvement_metrics,
                **improvement_source,
            },
            "equipmentDropFrom": {
                "schemaVersion": 1,
                "path": "equipment/drop-from.nedb",
                **datasets["dropFrom"]["metadata"],
            },
            "equipmentSpecialBonuses": {
                "schemaVersion": 2,
                "path": "equipment/special-bonuses.nedb",
                **datasets["specialBonuses"]["metadata"],
            },
            "equipmentSources": {
                "schemaVersion": 1,
                "path": "equipment/sources.nedb",
                "status": "ok",
                **equipment_source_incremental,
            },
            "useitemIcons": {
                "schemaVersion": 1,
                "directory": "assets/useitems",
                "count": len(available_icon_ids),
                "requiredIds": required_icon_ids,
                "availableIds": available_icon_ids,
                "missingIds": missing_icon_ids,
            },
        },
        "sources": {
            "akashiList": "https://akashi-list.me/",
            "kcwikiData": [SHIP_URL, EQUIPMENT_URL],
            "kcwikiQuests": datasets.get("questCatalog", {}).get("metadata", {}),
            "kc3SlotitemBonus": BONUS_URL,
        },
    }

    write_json(
        str(PACKAGE_DIR / "audit" / "build-report.json"),
        {
            "generatedAt": generated_at,
            "strict": strict,
            "improvementSourceStatus": improvement_source["status"],
            "dropFromIssueCount": len(datasets["dropFrom"]["issues"]),
            "specialBonusIssueCount": len(datasets["specialBonuses"]["issues"]),
            "equipmentSourceRecordCount": len(equipment_source_records),
            "equipmentAcquisitionInputMode": acquisition_snapshot.input_mode,
            "equipmentAcquisitionSnapshotGeneratedAt": acquisition_snapshot.metadata.get("generatedAt"),
            "equipmentSourceIncremental": equipment_source_incremental.get("incremental", {}),
            "improvement2Compatibility": improvement2_metrics,
            "iconCount": len(available_icon_ids),
            "requiredUseitemIconIds": required_icon_ids,
            "missingUseitemIconIds": missing_icon_ids,
        },
        mode="w",
        log=True,
    )

    write_json(str(PACKAGE_DIR / "manifest.json"), manifest, mode="w", log=True)
    manifest = refresh_package_manifest()
    simple_logger.info(f"[data package] built {PACKAGE_DIR}")
    return manifest


# Compatibility aliases for existing internal imports. New code should import the
# cohesive modules directly.
_clear_regenerated = clear_regenerated
_copy_file = copy_file
_copy_icon_directory = copy_icon_directory
_improvement_projection_metrics = improvement_projection_metrics
_improvement_source_metadata = improvement_source_metadata
_promote_cached_icons = promote_cached_icons
_required_useitem_ids = required_useitem_ids
