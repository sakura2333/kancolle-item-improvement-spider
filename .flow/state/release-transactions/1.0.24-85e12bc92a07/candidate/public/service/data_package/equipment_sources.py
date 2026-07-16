from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from service.operator_stop import OperatorStopError
from util.json_utils import read_json_lines, write_json, write_json_lines
from util.logger import simple_logger
from util.start2.start2_item_utils import Start2ItemUtils

SCHEMA_VERSION = 2
SOURCE_DATASET_ID = "equipment-sources"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _positive_int_values(values: Any) -> list[int]:
    result: set[int] = set()
    if not isinstance(values, (list, tuple, set)):
        return []
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            result.add(number)
    return sorted(result)


def _canonical_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for record in records:
        source = record.get("source") if isinstance(record.get("source"), dict) else {}
        normalized.append({
            "equipmentId": int(record["equipmentId"]),
            "equipmentName": str(record.get("equipmentName") or ""),
            "source": {
                "shipIds": _positive_int_values(source.get("shipIds", [])),
                "upgradeFromItemIds": _positive_int_values(
                    source.get("upgradeFromItemIds", [])
                ),
                "questKey": _positive_int_values(source.get("questKey", [])),
                "developmentAvailable": source.get("developmentAvailable"),
            },
        })
    return sorted(normalized, key=lambda value: value["equipmentId"])


def _read_nedb_strict(path: Path, *, stop_reason: str, action: str, checkpoint: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise OperatorStopError(
            stop_reason=stop_reason,
            message=f"canonical NEDB 不存在：{path}",
            action=action,
            checkpoint=checkpoint,
            details={"path": str(path)},
        )
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise OperatorStopError(
                    stop_reason=stop_reason,
                    message=f"canonical NEDB 损坏：{path}:{line_number}",
                    action=action,
                    checkpoint=checkpoint,
                    details={"path": str(path), "line": line_number, "error": str(exc)},
                ) from exc
            if not isinstance(value, dict):
                raise OperatorStopError(
                    stop_reason=stop_reason,
                    message=f"canonical NEDB 记录不是对象：{path}:{line_number}",
                    action=action,
                    checkpoint=checkpoint,
                    details={"path": str(path), "line": line_number},
                )
            records.append(value)
    return records


def build_upgrade_reverse_index(
    improvement_path: Path,
    item_utils: Start2ItemUtils,
) -> tuple[dict[int, set[int]], dict[str, int]]:
    records = _read_nedb_strict(
        improvement_path,
        stop_reason="canonical-improvement-nedb-invalid",
        action="恢复或重新生成 dist/packages/kancolle-data/improvement/detail.nedb，再从当前断点重试。",
        checkpoint=str(improvement_path),
    )
    known_ids = {
        int(item["api_id"])
        for item in item_utils.items
        if int(item.get("api_id") or 0) > 0
    }
    reverse: dict[int, set[int]] = defaultdict(set)
    route_count = 0
    relation_count = 0
    seen_source_ids: set[int] = set()
    for record_index, record in enumerate(records, 1):
        source_id = int(record.get("id") or 0)
        if source_id in seen_source_ids:
            raise OperatorStopError(
                stop_reason="canonical-improvement-duplicate-source",
                message=f"canonical improvement/detail.nedb 存在重复装备记录：{source_id}",
                action="修复 canonical NEDB 的重复记录后，从该文件断点重试。",
                checkpoint=str(improvement_path),
                details={"recordIndex": record_index, "sourceItemId": source_id},
            )
        seen_source_ids.add(source_id)
        if source_id not in known_ids:
            raise OperatorStopError(
                stop_reason="canonical-improvement-source-item-missing",
                message=f"改修记录引用不存在的起点装备 ID：{source_id}",
                action="修复 Start2 与 canonical improvement/detail.nedb 的版本一致性。",
                checkpoint=str(improvement_path),
                details={"recordIndex": record_index, "sourceItemId": source_id},
            )
        for route in record.get("improvementList", []):
            if not isinstance(route, dict):
                continue
            route_count += 1
            seen_targets: set[int] = set()
            for step in route.get("stepList", []):
                if not isinstance(step, dict) or step.get("action") != "upgrade" or not step.get("available"):
                    continue
                expected = step.get("expectedResult")
                target = expected.get("targetWeapon") if isinstance(expected, dict) else None
                target_id = int((target or {}).get("id") or 0) if isinstance(target, dict) else 0
                if target_id <= 0:
                    raise OperatorStopError(
                        stop_reason="canonical-upgrade-target-missing",
                        message=f"可用升级步骤缺少目标装备：source={source_id}",
                        action="修复 canonical improvement/detail.nedb 中该升级步骤。",
                        checkpoint=str(improvement_path),
                        details={"sourceItemId": source_id, "routeId": route.get("routeId")},
                    )
                if target_id not in known_ids:
                    raise OperatorStopError(
                        stop_reason="canonical-upgrade-target-item-missing",
                        message=f"升级目标装备不存在于 Start2：{target_id}",
                        action="更新 Start2 或修复 canonical improvement/detail.nedb 后重试。",
                        checkpoint=str(improvement_path),
                        details={"sourceItemId": source_id, "targetItemId": target_id},
                    )
                seen_targets.add(target_id)
            for target_id in seen_targets:
                if source_id not in reverse[target_id]:
                    reverse[target_id].add(source_id)
                    relation_count += 1
    return reverse, {
        "improvementRecordCount": len(records),
        "improvementRouteCount": route_count,
        "upgradeRelationCount": relation_count,
    }


def build_ship_index(drop_records: Iterable[dict[str, Any]]) -> tuple[dict[int, set[int]], int]:
    result: dict[int, set[int]] = defaultdict(set)
    relation_count = 0
    for record in drop_records:
        equipment_id = int(record.get("equipmentId") or 0)
        for source in record.get("sources", []):
            if not isinstance(source, dict):
                continue
            ship_id = int(source.get("shipId") or 0)
            if equipment_id > 0 and ship_id > 0 and ship_id not in result[equipment_id]:
                result[equipment_id].add(ship_id)
                relation_count += 1
    return result, relation_count


def build_quest_index(acquisition_records: Iterable[dict[str, Any]]) -> tuple[dict[int, set[int]], int]:
    result: dict[int, set[int]] = defaultdict(set)
    relation_count = 0
    for record in acquisition_records:
        if not record.get("accepted"):
            continue
        equipment_id = int(record.get("equipmentId") or 0)
        values = record.get("resolvedQuestKeys", [])
        for raw in values or []:
            quest_key = int(raw or 0)
            if equipment_id > 0 and quest_key > 0 and quest_key not in result[equipment_id]:
                result[equipment_id].add(quest_key)
                relation_count += 1
    return result, relation_count


def _development_stop(
    *,
    stop_reason: str,
    message: str,
    details: dict[str, Any],
) -> None:
    simple_logger.error(f"[EQUIPMENT DEVELOPMENT SOURCE ERROR] {message}; details={details}")
    raise OperatorStopError(
        stop_reason=stop_reason,
        message=message,
        action=(
            "检查 KCWiki _buildable 投影、WikiWiki 装备信息表解析及开发状态交叉验证；"
            "修复来源证据后重新生成，禁止 null 或冲突值进入正式包。"
        ),
        checkpoint="dist/data-pipeline/sources/equipment-sources",
        details=details,
    )


def build_kcwiki_development_index(
    records: Iterable[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    invalid: list[dict[str, Any]] = []
    for record_index, record in enumerate(records, 1):
        equipment_id = int(record.get("equipmentId") or 0)
        value = record.get("developmentAvailable")
        if equipment_id <= 0 or not isinstance(value, bool):
            invalid.append({
                "recordIndex": record_index,
                "equipmentId": equipment_id,
                "equipmentName": record.get("equipmentName"),
                "developmentAvailable": value,
                "valueType": type(value).__name__,
            })
            continue
        if equipment_id in result:
            invalid.append({
                "recordIndex": record_index,
                "equipmentId": equipment_id,
                "equipmentName": record.get("equipmentName"),
                "reason": "duplicate-equipment-id",
            })
            continue
        result[equipment_id] = record
    if invalid:
        _development_stop(
            stop_reason="kcwiki-development-flag-invalid",
            message="KCWiki 开发标记存在非布尔、缺失或重复记录。",
            details={"issueCount": len(invalid), "issues": invalid[:50]},
        )
    return result


def build_wikiwiki_development_index(
    records: Iterable[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    invalid: list[dict[str, Any]] = []
    for record_index, record in enumerate(records, 1):
        if record.get("accepted") is not True:
            continue
        equipment_id = int(record.get("equipmentId") or 0)
        value = record.get("developmentAvailable")
        if equipment_id <= 0 or not isinstance(value, bool):
            issue = {
                "recordIndex": record_index,
                "equipmentId": equipment_id,
                "equipmentName": record.get("equipmentName"),
                "sourceUrl": record.get("sourceUrl"),
                "developmentAvailable": value,
                "valueType": type(value).__name__,
                "developmentResolution": record.get("developmentResolution"),
            }
            invalid.append(issue)
            simple_logger.error(
                "[WIKIWIKI DEVELOPMENT FLAG UNRESOLVED] "
                f"equipment={equipment_id}:{record.get('equipmentName')}; "
                f"source={record.get('sourceUrl')}; "
                f"resolution={record.get('developmentResolution')}"
            )
            continue
        previous = result.get(equipment_id)
        if previous is not None:
            invalid.append({
                "recordIndex": record_index,
                "equipmentId": equipment_id,
                "equipmentName": record.get("equipmentName"),
                "reason": "duplicate-equipment-id",
            })
            continue
        result[equipment_id] = record
    if invalid:
        _development_stop(
            stop_reason="wikiwiki-development-flag-unresolved",
            message="WikiWiki 开发标记存在 null、缺失、非布尔或重复记录。",
            details={"issueCount": len(invalid), "issues": invalid[:50]},
        )
    return result


def _record_map(records: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(record["equipmentId"]): record for record in _canonical_records(records)}


def diff_records(previous: Iterable[dict[str, Any]], current: Iterable[dict[str, Any]]) -> dict[str, Any]:
    before = _record_map(previous)
    after = _record_map(current)
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(item_id for item_id in set(before) & set(after) if before[item_id] != after[item_id])
    unchanged = len(set(before) & set(after)) - len(changed)
    return {
        "addedIds": added,
        "changedIds": changed,
        "removedIds": removed,
        "unchangedCount": unchanged,
        "changed": bool(added or changed or removed),
    }


def build_equipment_source_records(
    *,
    item_utils: Start2ItemUtils,
    drop_records: Iterable[dict[str, Any]],
    improvement_path: Path,
    acquisition_records: Iterable[dict[str, Any]] = (),
    development_records: Iterable[dict[str, Any]] = (),
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    acquisition_records = list(acquisition_records)
    development_records = list(development_records)
    ship_index, ship_relation_count = build_ship_index(drop_records)
    upgrade_index, upgrade_metrics = build_upgrade_reverse_index(improvement_path, item_utils)
    quest_index, quest_relation_count = build_quest_index(acquisition_records)
    kcwiki_development = build_kcwiki_development_index(development_records)
    wikiwiki_development = build_wikiwiki_development_index(acquisition_records)
    records: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    missing_kcwiki: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    validation_counts: defaultdict[str, int] = defaultdict(int)
    available_count = 0
    for item in item_utils.items:
        equipment_id = int(item.get("api_id") or 0)
        if equipment_id <= 0 or int(item.get("api_sortno") or 0) <= 0:
            continue
        equipment_name = str(item.get("api_name") or "")
        kcwiki_record = kcwiki_development.get(equipment_id)
        if kcwiki_record is None:
            missing_kcwiki.append({
                "equipmentId": equipment_id,
                "equipmentName": equipment_name,
            })
            continue
        development_available = kcwiki_record["developmentAvailable"]
        available_count += int(development_available)
        wikiwiki_record = wikiwiki_development.get(equipment_id)
        diagnostic: dict[str, Any] = {
            "equipmentId": equipment_id,
            "equipmentName": equipment_name,
            "kcwiki": {
                "developmentAvailable": development_available,
                "evidence": kcwiki_record.get("evidence", {}),
            },
        }
        if wikiwiki_record is None:
            status = "wikiwiki-missing"
        else:
            wikiwiki_value = wikiwiki_record["developmentAvailable"]
            diagnostic["wikiwiki"] = {
                "developmentAvailable": wikiwiki_value,
                "sourceUrl": wikiwiki_record.get("sourceUrl"),
                "resolution": wikiwiki_record.get("developmentResolution", {}),
            }
            status = "matched" if wikiwiki_value == development_available else "conflict"
            if status == "conflict":
                conflicts.append(diagnostic)
        diagnostic["status"] = status
        validation_counts[status] += 1
        diagnostics.append(diagnostic)
        records.append({
            "equipmentId": equipment_id,
            "equipmentName": equipment_name,
            "source": {
                "shipIds": sorted(ship_index.get(equipment_id, set())),
                "upgradeFromItemIds": sorted(upgrade_index.get(equipment_id, set())),
                "questKey": sorted(quest_index.get(equipment_id, set())),
                "developmentAvailable": development_available,
            },
        })
    wikiwiki_missing_count = int(validation_counts.get("wikiwiki-missing", 0))
    if wikiwiki_missing_count:
        simple_logger.warning(
            "[EQUIPMENT DEVELOPMENT CROSS-VALIDATION INCOMPLETE] "
            f"wikiwikiMissing={wikiwiki_missing_count}; "
            "formal values remain sourced from KCWiki _buildable"
        )
    if missing_kcwiki:
        _development_stop(
            stop_reason="kcwiki-development-coverage-incomplete",
            message="KCWiki 开发标记未覆盖全部 Start2 玩家装备。",
            details={
                "missingCount": len(missing_kcwiki),
                "missing": missing_kcwiki[:50],
            },
        )
    if conflicts:
        _development_stop(
            stop_reason="equipment-development-source-conflict",
            message="KCWiki 与 WikiWiki 的装备开发标记交叉验证不一致。",
            details={
                "conflictCount": len(conflicts),
                "conflicts": conflicts[:50],
            },
        )
    records = _canonical_records(records)
    metadata = {
        "source": SOURCE_DATASET_ID,
        "schemaVersion": SCHEMA_VERSION,
        "equipmentRecordCount": len(records),
        "shipRelationCount": ship_relation_count,
        "questRelationCount": quest_relation_count,
        "developmentAvailableCount": available_count,
        "developmentUnavailableCount": len(records) - available_count,
        "developmentCrossValidation": {
            "kcwikiAuthority": "_buildable matched by normalized Japanese name",
            "wikiwikiEvidence": "current equipment infobox 備考 row",
            "matchedCount": int(validation_counts.get("matched", 0)),
            "wikiwikiMissingCount": wikiwiki_missing_count,
            "conflictCount": int(validation_counts.get("conflict", 0)),
            "diagnosticRecordCount": len(diagnostics),
        },
        **upgrade_metrics,
    }
    return records, metadata, diagnostics


def write_incremental_source_bundle(
    *,
    records: list[dict[str, Any]],
    output_path: Path,
    metadata_path: Path,
    changes_path: Path,
    metadata: dict[str, Any],
    input_hashes: dict[str, str | None],
) -> dict[str, Any]:
    previous = read_json_lines(output_path)
    diff = diff_records(previous, records)
    if diff["changed"] or not output_path.is_file():
        write_json_lines(output_path, records, log=False)
    change_rows = [
        {"equipmentId": item_id, "change": kind}
        for kind, ids in (
            ("added", diff["addedIds"]),
            ("changed", diff["changedIds"]),
            ("removed", diff["removedIds"]),
        )
        for item_id in ids
    ]
    write_json_lines(changes_path, change_rows, log=False)
    final_metadata = {
        **metadata,
        "incremental": {
            **diff,
            "inputHashes": input_hashes,
            "projectionSha256": _sha256(output_path) if output_path.is_file() else None,
        },
    }
    write_json(metadata_path, final_metadata, log=False)
    return final_metadata
