from __future__ import annotations

import json
from typing import Any, Dict

from service.data_package.equipment_bonus import SOURCE_URL as BONUS_URL, parse_special_bonuses
from service.data_package.equipment_development import parse_kcwiki_development_flags
from service.data_package.equipment_drop_from import EQUIPMENT_URL, SHIP_URL, parse_drop_from
from service.data_package.acquisition_references import QUEST_DATA_URL, QuestReferenceCatalog
from service.data_package.package_paths import AKASHI_METADATA_PATH, AKASHI_URL, SOURCE_ROOT
from service.operator_stop import OperatorStopError
from service.source_validation.semantic_aliases import validate_semantic_alias_dictionary
from util.cache import collection_completed_in_run, fetch, get_fetch_meta
from util.json_utils import read_json_lines, write_json, write_json_lines
from util.logger import simple_logger
from util.start2.start2_item_utils import start2ItemUtils
from util.start2.start2_ship_utils import ship_utils



def _read_json_object(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _record_map(records: list[dict]) -> dict[int, str]:
    result: dict[int, str] = {}
    for record in records:
        try:
            equipment_id = int(record.get("equipmentId") or 0)
        except (TypeError, ValueError):
            continue
        if equipment_id > 0:
            result[equipment_id] = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return result


def _record_diff(previous: list[dict], current: list[dict]) -> dict:
    before = _record_map(previous)
    after = _record_map(current)
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(key for key in set(before) & set(after) if before[key] != after[key])
    return {
        "addedIds": added,
        "changedIds": changed,
        "removedIds": removed,
        "unchangedCount": len(set(before) & set(after)) - len(changed),
        "changed": bool(added or changed or removed),
    }

def _load_json(
    url: str,
    *,
    require_fresh: bool | None = None,
) -> tuple[Any, dict]:
    value = json.loads(fetch(url, require_fresh=require_fresh))
    return value, _fetch_summary(url)

def _fetch_summary(url: str) -> dict:
    meta = get_fetch_meta(url)
    return {
        "url": url,
        "status": meta.get("fetch_status", "unknown"),
        "statusCode": meta.get("status_code"),
        "validatedAt": meta.get("validated_at"),
        "validatedInRun": bool(meta.get("validated_in_run")),
        "usedCacheFallback": bool(meta.get("used_cache_fallback")),
        "contentSha256": meta.get("content_sha256"),
        "cachePath": meta.get("cache_path"),
    }

def _source_status(fetches: list[dict]) -> str:
    if fetches and all(
        info.get("status") == "fresh"
        and info.get("validatedInRun")
        and not info.get("usedCacheFallback")
        for info in fetches
    ):
        return "ok"
    return "stale"

def _improvement_source_metadata(strict: bool) -> dict:
    source_metadata: dict[str, Any] = {}
    if AKASHI_METADATA_PATH.is_file():
        try:
            loaded = json.loads(AKASHI_METADATA_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                source_metadata = loaded
        except Exception as exc:
            if strict:
                raise ValueError(f"invalid Akashi source metadata: {exc}") from exc
            simple_logger.warning(f"[data package] invalid Akashi source metadata: {exc}")

    fetches = [_fetch_summary(AKASHI_URL)]
    status = "ok" if (
        source_metadata.get("status") == "ok"
        and source_metadata.get("scheduleCount", 0) > 0
        and _source_status(fetches) == "ok"
        and collection_completed_in_run("akashi-list")
    ) else "stale"
    metadata = {
        "source": "akashi-list",
        "sourceUrl": AKASHI_URL,
        "status": status,
        "fetches": fetches,
        "sourceScheduleCount": int(source_metadata.get("scheduleCount", 0) or 0),
        "sourceIssueCount": int(source_metadata.get("issueCount", 0) or 0),
        "sourceGeneratedAt": source_metadata.get("generatedAt"),
        "collectionCompletedInRun": collection_completed_in_run("akashi-list"),
    }
    if strict and status != "ok":
        raise ValueError(
            "Akashi improvement data was not freshly validated in this strict run; "
            "run the strict Spider instead of packaging existing projections"
        )
    return metadata

def _export_source_bundle(source: str, records: list, issues: list, metadata: dict, file_name: str):
    directory = SOURCE_ROOT / source
    directory.mkdir(parents=True, exist_ok=True)
    write_json_lines(str(directory / file_name), records, mode="w", log=True)
    write_json_lines(
        str(directory / "dataset-issues.nedb"),
        [issue.to_json() for issue in issues],
        mode="w",
        log=True,
    )
    write_json(str(directory / "dataset-metadata.json"), metadata, mode="w", log=True)

def collect_optional_datasets(strict: bool = False) -> dict:
    item_utils = start2ItemUtils.load()
    ships = ship_utils.load()
    alias_validation = validate_semantic_alias_dictionary(item_utils, ships)
    simple_logger.info(
        "[semantic aliases] "
        f"validated={alias_validation['validatedTargetCount']}/"
        f"{alias_validation['entryCount']} against Start2"
    )
    result: Dict[str, Any] = {}

    kcwiki_raw_loaded = False
    try:
        ship_catalog, ship_fetch = _load_json(SHIP_URL, require_fresh=False)
        equipment_catalog, equipment_fetch = _load_json(EQUIPMENT_URL, require_fresh=False)
        kcwiki_raw_loaded = True
        fetches = [ship_fetch, equipment_fetch]
        source_dir = SOURCE_ROOT / "kcwiki-data"
        record_path = source_dir / "equipment-drop-from.nedb"
        issue_path = source_dir / "dataset-issues.nedb"
        metadata_path = source_dir / "dataset-metadata.json"
        previous_metadata = _read_json_object(metadata_path)
        input_hashes = {
            "ship": ship_fetch.get("contentSha256"),
            "equipment": equipment_fetch.get("contentSha256"),
        }
        development_records, development_issues, development_metadata = (
            parse_kcwiki_development_flags(equipment_catalog, item_utils)
        )
        development_metadata = {
            **development_metadata,
            "status": _source_status([equipment_fetch]),
            "fetches": [equipment_fetch],
            "inputHashes": {"equipment": equipment_fetch.get("contentSha256")},
        }
        _export_source_bundle(
            "kcwiki-equipment-development",
            development_records,
            development_issues,
            development_metadata,
            "development-flags.nedb",
        )
        result["developmentFlags"] = {
            "records": development_records,
            "issues": development_issues,
            "metadata": development_metadata,
        }
        if development_issues:
            first = development_issues[0].to_json()
            simple_logger.error(
                "[KCWIKI DEVELOPMENT FLAG INVALID] "
                f"issues={len(development_issues)} first={first}"
            )
            if strict:
                raise OperatorStopError(
                    stop_reason=str(first.get("kind") or "kcwiki-development-flag-invalid"),
                    message=(
                        "KCWiki _buildable 投影存在无法解析为非空布尔值的记录："
                        f"{len(development_issues)}"
                    ),
                    action=(
                        "检查 kcwiki equipment.json 的 _buildable 与日文名映射；"
                        "不得使用跨来源数字 ID 兜底。"
                    ),
                    checkpoint=str(SOURCE_ROOT / "kcwiki-equipment-development"),
                    details={"issueCount": len(development_issues), "firstIssue": first},
                )
        simple_logger.info(
            "[data source] kcwiki-equipment-development: "
            f"status={development_metadata['status']}, "
            f"records={development_metadata['recordCount']}, "
            f"available={development_metadata['developmentAvailableCount']}, "
            f"unavailable={development_metadata['developmentUnavailableCount']}, "
            f"issues={development_metadata['issueCount']}"
        )
        previous_records = read_json_lines(record_path)
        can_reuse = (
            bool(previous_records)
            and all(input_hashes.values())
            and previous_metadata.get("inputHashes") == input_hashes
            and record_path.is_file()
            and issue_path.is_file()
        )
        if can_reuse:
            records = previous_records
            issues = read_json_lines(issue_path)
            metadata = {
                **previous_metadata,
                "status": _source_status(fetches),
                "fetches": fetches,
                "inputHashes": input_hashes,
                "incremental": {
                    "mode": "reuse-unchanged-inputs",
                    "parsed": False,
                    "changed": False,
                    "addedIds": [],
                    "changedIds": [],
                    "removedIds": [],
                    "unchangedCount": len(records),
                },
            }
            write_json(str(metadata_path), metadata, mode="w", log=False)
        else:
            records, issues, metadata = parse_drop_from(
                ship_catalog,
                equipment_catalog,
                item_utils,
                ships,
            )
            if not records or int(metadata.get("relationCount", 0)) <= 0:
                raise ValueError("KcWiki drop-from source parsed no usable equipment relations")
            diff = _record_diff(previous_records, records)
            metadata = {
                **metadata,
                "status": _source_status(fetches),
                "fetches": fetches,
                "inputHashes": input_hashes,
                "incremental": {"mode": "parsed", "parsed": True, **diff},
            }
            _export_source_bundle(
                "kcwiki-data", records, issues, metadata, "equipment-drop-from.nedb"
            )
        if strict and issues:
            first = issues[0]
            payload = first.to_json() if hasattr(first, "to_json") else dict(first)
            kind = str(payload.get("kind") or "kcwiki-mapping-conflict")
            raise OperatorStopError(
                stop_reason=kind,
                message=f"KcWiki 来源存在 {len(issues)} 个无法自动确认的映射问题。",
                action="检查 dataset-issues.nedb；修正权威数据冲突或人工接受映射后重试。",
                checkpoint=str(source_dir / "dataset-issues.nedb"),
                details={"issueCount": len(issues), "firstIssue": payload},
            )
        simple_logger.info(
            "[data source] kcwiki-data: "
            f"status={metadata['status']}, relations={metadata['relationCount']}, "
            f"issues={metadata['issueCount']}, "
            f"incremental={metadata['incremental']['mode']}, "
            f"semanticAliases={metadata.get('semanticAliasMatchCount', 0)}"
        )
        result["dropFrom"] = {"records": records, "issues": issues, "metadata": metadata}
    except Exception as exc:
        if kcwiki_raw_loaded:
            simple_logger.error(
                f"[data package] equipment drop-from collection failed: {exc}"
            )
        else:
            simple_logger.error(
                "[KCWIKI RAW UNAVAILABLE][NON-BLOCKING] "
                f"equipment drop-from refresh skipped: {type(exc).__name__}: {exc}"
            )
        result["dropFrom"] = {
            "records": [],
            "issues": [],
            "metadata": {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "sourceUrls": [SHIP_URL, EQUIPMENT_URL],
            },
        }
        if strict and kcwiki_raw_loaded:
            raise

    try:
        quest_catalog, quest_fetch = _load_json(QUEST_DATA_URL)
        quest_index = QuestReferenceCatalog.from_json_text(
            json.dumps(quest_catalog, ensure_ascii=False)
        )
        quest_fetches = [quest_fetch]
        quest_metadata = {
            "source": "kcwikizh-kcquests",
            "sourceUrl": QUEST_DATA_URL,
            "status": _source_status(quest_fetches),
            "fetches": quest_fetches,
            "questCount": len(quest_index.records),
            "schemaVersion": 1,
        }
        result["questCatalog"] = {
            "catalog": quest_catalog,
            "metadata": quest_metadata,
        }
        simple_logger.info(
            "[data source] kcwikizh-kcquests: "
            f"status={quest_metadata['status']}, quests={quest_metadata['questCount']}"
        )
    except Exception as exc:
        simple_logger.error(f"[data package] quest catalog collection failed: {exc}")
        result["questCatalog"] = {
            "catalog": None,
            "metadata": {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "sourceUrl": QUEST_DATA_URL,
            },
        }
        if strict:
            raise OperatorStopError(
                stop_reason="quest-catalog-invalid",
                message=f"kcQuests 任务目录无法获取或校验：{exc}",
                action="检查网络或缓存，确认 quests-scn.json 顶层为数字 questKey 后重试。",
                checkpoint=str(SOURCE_ROOT / "wikiwiki-equipment-detail"),
                details={"sourceUrl": QUEST_DATA_URL},
            ) from exc

    try:
        bonus_catalog, bonus_fetch = _load_json(BONUS_URL)
        records, issues, metadata = parse_special_bonuses(bonus_catalog, item_utils, ships)
        if not records or int(metadata.get("ruleCount", 0)) <= 0:
            raise ValueError("KC3 slot-item bonus source parsed no usable bonus rules")
        fetches = [bonus_fetch]
        metadata = {
            **metadata,
            "status": _source_status(fetches),
            "fetches": fetches,
        }
        _export_source_bundle(
            "kc3-slotitem-bonus",
            records,
            issues,
            metadata,
            "special-bonuses.nedb",
        )
        result["specialBonuses"] = {"records": records, "issues": issues, "metadata": metadata}
    except Exception as exc:
        simple_logger.error(f"[data package] special bonus collection failed: {exc}")
        result["specialBonuses"] = {
            "records": [],
            "issues": [],
            "metadata": {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "sourceUrl": BONUS_URL,
            },
        }
        if strict:
            raise

    return result

