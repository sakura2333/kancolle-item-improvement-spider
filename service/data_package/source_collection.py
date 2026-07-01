from __future__ import annotations

import json
from typing import Any, Dict

from service.data_package.equipment_bonus import SOURCE_URL as BONUS_URL, parse_special_bonuses
from service.data_package.equipment_drop_from import EQUIPMENT_URL, SHIP_URL, parse_drop_from
from service.data_package.package_paths import AKASHI_METADATA_PATH, AKASHI_URL, SOURCE_ROOT
from util.cache import collection_completed_in_run, fetch, get_fetch_meta
from util.json_utils import write_json, write_json_lines
from util.logger import simple_logger
from util.start2.start2_item_utils import start2ItemUtils
from util.start2.start2_ship_utils import ship_utils

def _load_json(url: str) -> tuple[Any, dict]:
    value = json.loads(fetch(url))
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
    result: Dict[str, Any] = {}

    try:
        ship_catalog, ship_fetch = _load_json(SHIP_URL)
        equipment_catalog, equipment_fetch = _load_json(EQUIPMENT_URL)
        records, issues, metadata = parse_drop_from(
            ship_catalog,
            equipment_catalog,
            item_utils,
            ships,
        )
        if not records or int(metadata.get("relationCount", 0)) <= 0:
            raise ValueError("KcWiki drop-from source parsed no usable equipment relations")
        fetches = [ship_fetch, equipment_fetch]
        metadata = {
            **metadata,
            "status": _source_status(fetches),
            "fetches": fetches,
        }
        _export_source_bundle(
            "kcwiki-data",
            records,
            issues,
            metadata,
            "equipment-drop-from.nedb",
        )
        result["dropFrom"] = {"records": records, "issues": issues, "metadata": metadata}
    except Exception as exc:
        simple_logger.error(f"[data package] equipment drop-from collection failed: {exc}")
        result["dropFrom"] = {
            "records": [],
            "issues": [],
            "metadata": {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "sourceUrls": [SHIP_URL, EQUIPMENT_URL],
            },
        }
        if strict:
            raise

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

