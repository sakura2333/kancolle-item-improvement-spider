from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

from service.data_package.equipment_bonus import SOURCE_URL as BONUS_URL
from service.data_package.equipment_drop_from import EQUIPMENT_URL, SHIP_URL
from service.data_package.manifest_builder import package_version, refresh_package_manifest
from service.data_package.package_paths import (
    AKASHI_METADATA_PATH,
    AKASHI_URL,
    CACHE_IMAGE_DIR,
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
from util.json_utils import write_json, write_json_lines
from util.logger import simple_logger

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
