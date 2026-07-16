from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from service.data_package.builder import PACKAGE_DIR

from .assets import _validate_icons
from .common import QualityGateError, _read_json, _sha256
from .constants import PUBLIC_DATA_PREFIXES
from .equipment import (
    _validate_drop_from,
    _validate_equipment_sources,
    _validate_special_bonuses,
)
from .improvement import (
    _validate_improvement2_compatibility,
    _validate_improvement_detail,
    _validate_improvement_list,
)

def inspect_package(package_dir: Path = PACKAGE_DIR, require_fresh_sources: bool = True) -> dict:
    package_dir = Path(package_dir)
    required = [
        package_dir / "manifest.json",
        package_dir / "improvement" / "list.json",
        package_dir / "improvement" / "detail.nedb",
        package_dir / "compat" / "poi-plugin-item-improvement2" / "manifest.json",
        package_dir / "compat" / "poi-plugin-item-improvement2" / "improvement" / "list.json",
        package_dir / "compat" / "poi-plugin-item-improvement2" / "improvement" / "detail.nedb",
        package_dir / "equipment" / "drop-from.nedb",
        package_dir / "equipment" / "sources.nedb",
        package_dir / "equipment" / "special-bonuses.nedb",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise QualityGateError(f"missing package files: {', '.join(missing)}")

    manifest = _read_json(package_dir / "manifest.json")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("datasets"), dict):
        raise QualityGateError("manifest.json has invalid structure")
    expected_schemas = {
        "improvement": 4,
        "equipmentDropFrom": 1,
        "equipmentSources": 1,
        "equipmentSpecialBonuses": 2,
        "equipmentImages": 1,
        "useitemIcons": 1,
    }
    for key, expected in expected_schemas.items():
        actual = manifest["datasets"].get(key, {}).get("schemaVersion")
        if actual != expected:
            raise QualityGateError(f"unsupported {key} schema: expected {expected}, got {actual!r}")
    if require_fresh_sources:
        for key in ("improvement", "equipmentDropFrom", "equipmentSpecialBonuses"):
            dataset = manifest["datasets"].get(key, {})
            status = dataset.get("status")
            if status != "ok":
                raise QualityGateError(f"dataset {key} is not fresh: status={status!r}")
            if key == "improvement" and dataset.get("collectionCompletedInRun") is not True:
                raise QualityGateError("dataset improvement was not rebuilt by the canonical Spider in this run")
            fetches = dataset.get("fetches")
            if not isinstance(fetches, list) or not fetches:
                raise QualityGateError(f"dataset {key} has no fetch audit")
            for fetch_info in fetches:
                if not isinstance(fetch_info, dict):
                    raise QualityGateError(f"dataset {key} has invalid fetch audit")
                if fetch_info.get("status") != "fresh":
                    raise QualityGateError(
                        f"dataset {key} source is not fresh: {fetch_info.get('url')} status={fetch_info.get('status')!r}"
                    )
                if not fetch_info.get("validatedInRun") or fetch_info.get("usedCacheFallback"):
                    raise QualityGateError(
                        f"dataset {key} source was not revalidated in this run: {fetch_info.get('url')}"
                    )

    view_count, list_all_count, list_ids = _validate_improvement_list(package_dir / "improvement" / "list.json")
    detail_count, detail_ids, required_icon_ids, improvement_metrics = _validate_improvement_detail(
        package_dir / "improvement" / "detail.nedb"
    )
    if list_ids != detail_ids:
        missing_in_list = sorted(detail_ids - list_ids)[:10]
        missing_in_detail = sorted(list_ids - detail_ids)[:10]
        raise QualityGateError(
            "improvement list/detail id mismatch: "
            f"missingInList={missing_in_list}, missingInDetail={missing_in_detail}"
        )
    compatibility_root = package_dir / "compat" / "poi-plugin-item-improvement2"
    compatibility_manifest = _read_json(compatibility_root / "manifest.json")
    if not isinstance(compatibility_manifest, dict):
        raise QualityGateError("improvement2 compatibility manifest is invalid")
    compatibility_dataset = compatibility_manifest.get("datasets", {}).get(
        "improvement", {}
    )
    if compatibility_manifest.get("consumer") != "poi-plugin-item-improvement2":
        raise QualityGateError("improvement2 compatibility manifest has invalid consumer")
    if compatibility_dataset.get("schemaVersion") != 3:
        raise QualityGateError("improvement2 compatibility manifest must expose schema 3")
    if compatibility_dataset.get("listSchemaVersion") != 2:
        raise QualityGateError("improvement2 compatibility list schema must remain 2")
    if compatibility_dataset.get("list") != "improvement/list.json":
        raise QualityGateError("improvement2 compatibility manifest has invalid list path")
    if compatibility_dataset.get("detail") != "improvement/detail.nedb":
        raise QualityGateError("improvement2 compatibility manifest has invalid detail path")
    if (compatibility_root / "improvement" / "list.json").read_bytes() != (
        package_dir / "improvement" / "list.json"
    ).read_bytes():
        raise QualityGateError("improvement2 compatibility list must reuse the canonical schema-2 list")
    compat_count, compat_route_count, compat_ids = _validate_improvement2_compatibility(
        package_dir / "improvement" / "detail.nedb",
        compatibility_root / "improvement" / "detail.nedb",
    )
    if compat_ids != detail_ids:
        raise QualityGateError("improvement2 compatibility ids do not match canonical detail")
    drop_count, relation_count = _validate_drop_from(package_dir / "equipment" / "drop-from.nedb")
    source_count, source_ship_count, source_upgrade_count, source_quest_count = (
        _validate_equipment_sources(package_dir / "equipment" / "sources.nedb")
    )
    bonus_count, bonus_equipment_count, bonus_type_count, rule_count = _validate_special_bonuses(
        package_dir / "equipment" / "special-bonuses.nedb"
    )
    icon_ids = _validate_icons(package_dir / "assets" / "useitem")
    missing_icon_ids = sorted(required_icon_ids - icon_ids)
    if missing_icon_ids:
        raise QualityGateError(f"required use-item icons are missing: {missing_icon_ids}")
    icon_count = len(icon_ids)
    icon_manifest = manifest["datasets"].get("useitemIcons", {})
    if sorted(icon_manifest.get("requiredIds", [])) != sorted(required_icon_ids):
        raise QualityGateError("useitem icon manifest requiredIds do not match improvement detail references")
    if sorted(icon_manifest.get("availableIds", [])) != sorted(icon_ids):
        raise QualityGateError("useitem icon manifest availableIds do not match packaged PNG files")
    if icon_manifest.get("missingIds") not in ([], None):
        raise QualityGateError(f"useitem icon manifest reports missing ids: {icon_manifest.get('missingIds')}")
    equipment_image_ids = _validate_icons(package_dir / "assets" / "equipment")
    equipment_image_manifest = manifest["datasets"].get("equipmentImages", {})
    if sorted(equipment_image_manifest.get("availableIds", [])) != sorted(equipment_image_ids):
        raise QualityGateError("equipment image manifest availableIds do not match packaged PNG files")

    files: dict[str, dict[str, Any]] = {}
    digest = hashlib.sha256()
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(package_dir).as_posix()
        if not relative.startswith(PUBLIC_DATA_PREFIXES):
            continue
        sha256 = _sha256(path)
        files[relative] = {"bytes": path.stat().st_size, "sha256": sha256}
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256.encode("ascii"))
        digest.update(b"\n")

    total_public_bytes = sum(file_info["bytes"] for file_info in files.values())
    icon_total_bytes = sum(
        file_info["bytes"] for relative, file_info in files.items()
        if relative.startswith("assets/useitem/")
    )
    equipment_image_total_bytes = sum(
        file_info["bytes"] for relative, file_info in files.items()
        if relative.startswith("assets/equip/")
    )

    return {
        "snapshotVersion": 1,
        "createdAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "contentDigest": digest.hexdigest(),
        "metrics": {
            "improvement.listViewCount": view_count,
            "improvement.listAllCount": list_all_count,
            "improvement.detailRecordCount": detail_count,
            "improvement.effectExpectationAvailableCount": improvement_metrics["effectExpectationAvailableCount"],
            "improvement.effectExpectationUnavailableCount": improvement_metrics["effectExpectationUnavailableCount"],
            "improvement.routeCount": improvement_metrics["routeCount"],
            "improvement.stepCount": improvement_metrics["stepCount"],
            "improvement.upgradeAvailableCount": improvement_metrics["upgradeAvailableCount"],
            "compat.poiPluginItemImprovement2.detailRecordCount": compat_count,
            "compat.poiPluginItemImprovement2.routeCount": compat_route_count,
            "equipmentDropFrom.recordCount": drop_count,
            "equipmentDropFrom.relationCount": relation_count,
            "equipmentSources.recordCount": source_count,
            "equipmentSources.shipRelationCount": source_ship_count,
            "equipmentSources.upgradeRelationCount": source_upgrade_count,
            "equipmentSources.questRelationCount": source_quest_count,
            "equipmentSpecialBonuses.recordCount": bonus_count,
            "equipmentSpecialBonuses.equipmentRecordCount": bonus_equipment_count,
            "equipmentSpecialBonuses.equipmentTypeRecordCount": bonus_type_count,
            "equipmentSpecialBonuses.ruleCount": rule_count,
            "useitemIcons.requiredCount": len(required_icon_ids),
            "useitemIcons.missingCount": len(missing_icon_ids),
            "useitemIcons.count": icon_count,
            "useitemIcons.totalBytes": icon_total_bytes,
            "equipmentImages.count": len(equipment_image_ids),
            "equipmentImages.totalBytes": equipment_image_total_bytes,
            "publicData.totalBytes": total_public_bytes,
        },
        "files": files,
    }

def write_snapshot(output: Path, package_dir: Path = PACKAGE_DIR, require_fresh_sources: bool = False) -> dict:
    snapshot = inspect_package(package_dir=package_dir, require_fresh_sources=require_fresh_sources)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return snapshot
