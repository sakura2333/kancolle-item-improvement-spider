from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from service.source_validation.common import CatalogMatcher, merge_schedules, normalize_catalog_name
from service.source_validation.model import SourceIssue, SourceResult, SourceSchedule, normalize_week
from util.cache import fetch
from util.start2.start2_item_utils import Start2ItemUtils
from util.start2.start2_ship_utils import Start2ShipUtils

SOURCE_ID = "kcwiki-data"
EQUIPMENT_URL = "https://raw.githubusercontent.com/kcwiki/kancolle-data/refs/heads/master/wiki/equipment.json"
SHIP_URL = "https://raw.githubusercontent.com/kcwiki/kancolle-data/refs/heads/master/wiki/ship.json"
DAY_KEYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def _positive_int(value) -> Optional[int]:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _compact_ref(value: str) -> str:
    value = str(value or "").strip().replace("\\", "/")
    value = re.sub(r"\s+", " ", value)
    return value.lower()


def _walk_catalog(node: Any, path: Tuple[str, ...] = ()): 
    if isinstance(node, dict):
        yield node, path
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                next_path = path if str(key).startswith("_") else path + (str(key),)
                yield from _walk_catalog(value, next_path)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, (dict, list)):
                yield from _walk_catalog(value, path + (str(index),))


def build_ship_reference_map(catalog: Any, ship_utils: Start2ShipUtils) -> Dict[str, List[int]]:
    aliases: Dict[str, List[int]] = defaultdict(list)

    def add(alias: str, ship_id: int):
        key = _compact_ref(alias)
        if key and ship_id not in aliases[key]:
            aliases[key].append(ship_id)

    def resolve_ship_by_name(raw_name: Any) -> Optional[int]:
        if not raw_name:
            return None
        normalized = normalize_catalog_name(str(raw_name))
        matches = [
            ship for ship in ship_utils.ships
            if normalize_catalog_name(ship.get("api_name") or "") == normalized
        ]
        if len(matches) == 1:
            return int(matches[0]["api_id"])
        return None

    for node, path in _walk_catalog(catalog):
        japanese_name = (
            node.get("_japanese_name")
            or node.get("_name_jp")
            or node.get("japanese_name")
        )
        ship_id = resolve_ship_by_name(japanese_name)
        if ship_id is None:
            continue

        if path:
            filtered = [part for part in path if not part.isdigit()]
            if filtered:
                add("/".join(filtered), ship_id)
                if len(filtered) == 1:
                    add(f"{filtered[0]}/", ship_id)
        base_name = node.get("_name") or node.get("name")
        full_name = node.get("_full_name") or node.get("full_name")
        for alias in (
            base_name,
            full_name,
            japanese_name,
        ):
            if alias:
                add(str(alias), ship_id)

        # KcWiki improvement references use slash-separated remodel names such
        # as ``Fubuki/Kai Ni`` while ship.json stores ``Fubuki Kai Ni``.
        if base_name and full_name:
            base_text = str(base_name).strip()
            full_text = str(full_name).strip()
            if full_text.lower().startswith(base_text.lower() + " "):
                suffix = full_text[len(base_text):].strip()
                if suffix:
                    add(f"{base_text}/{suffix}", ship_id)
                    if suffix.lower().startswith("kou "):
                        add(f"{base_text}/Carrier {suffix[4:]}", ship_id)
        if path:
            top_level_name = str(path[0]).strip()
            if base_name and top_level_name.lower().startswith(str(base_name).lower() + " "):
                suffix = top_level_name[len(str(base_name)):].strip()
                if suffix:
                    add(f"{base_name}/{suffix}", ship_id)

    # Names that are already Latin in start2 can be resolved without the wiki catalog.
    for ship in ship_utils.ships:
        name = str(ship.get("api_name") or "")
        if name:
            add(name, int(ship["api_id"]))
    return aliases


def _iter_ship_maps(node: Any, path: Tuple[str, ...] = ()):
    if isinstance(node, dict):
        ships = node.get("_ships")
        if isinstance(ships, dict):
            yield ships, path
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                yield from _iter_ship_maps(value, path + (str(key),))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iter_ship_maps(value, path + (str(index),))


def parse_kcwiki_data(
    equipment_catalog: Any,
    ship_catalog: Any,
    item_utils: Start2ItemUtils,
    ship_utils: Start2ShipUtils,
    source_url: str = EQUIPMENT_URL,
) -> SourceResult:
    matcher = CatalogMatcher(item_utils, ship_utils)
    ship_refs = build_ship_reference_map(ship_catalog, ship_utils)
    schedules: List[SourceSchedule] = []
    issues: List[SourceIssue] = []
    equipment_count = 0
    ship_map_count = 0

    entries = equipment_catalog.items() if isinstance(equipment_catalog, dict) else []
    for entry_name, entry in entries:
        if not isinstance(entry, dict):
            continue
        improvements = entry.get("_improvements")
        if not improvements:
            continue
        equipment_count += 1

        source_local_item_id = _positive_int(entry.get("_id"))
        japanese_name = entry.get("_japanese_name") or entry_name
        item = matcher.item(str(japanese_name))
        if item is None:
            issues.append(SourceIssue(
                source=SOURCE_ID,
                kind="unresolved-item",
                message="equipment entry was not found in start2",
                source_ref=source_url,
                item_name=str(entry.get("_japanese_name") or entry_name),
                raw_text=str(entry_name),
            ))
            continue

        canonical_item_id = int(item["api_id"])
        canonical_item_name = str(item.get("api_name") or entry_name)
        for ship_map, path in _iter_ship_maps(improvements):
            ship_map_count += 1
            for ship_ref, day_map in ship_map.items():
                if not isinstance(day_map, dict):
                    continue
                week = normalize_week(bool(day_map.get(day)) for day in DAY_KEYS)
                if not any(week):
                    continue

                compact_ship_ref = _compact_ref(ship_ref)
                no_specific_ship = compact_ship_ref == "true"
                ids = [None] if no_specific_ship else ship_refs.get(compact_ship_ref, [])
                if not ids:
                    issues.append(SourceIssue(
                        source=SOURCE_ID,
                        kind="unresolved-ship",
                        message="KcWiki ship reference was not mapped to start2",
                        source_ref=source_url,
                        item_name=canonical_item_name,
                        ship_name=str(ship_ref),
                        raw_text=str(ship_ref),
                        evidence={"path": list(path)},
                    ))
                    continue

                for ship_id in ids:
                    ship = ship_utils.get_by_id(ship_id) if ship_id is not None else None
                    schedules.append(SourceSchedule(
                        source=SOURCE_ID,
                        item_id=canonical_item_id,
                        item_name=canonical_item_name,
                        ship_id=ship_id,
                        ship_name=str((ship or {}).get("api_name") or ("" if ship_id is None else ship_ref)),
                        week=week,
                        route_id="/".join(path),
                        route_signature="/".join(path),
                        evidence_status="explicit-yes",
                        parser_version="kcwiki-structured-v3",
                        source_ref=source_url,
                        raw_text=str(ship_ref),
                        evidence={
                            "path": list(path),
                            "wikiEquipmentName": entry_name,
                            "sourceLocalEquipmentId": source_local_item_id,
                        },
                    ))

    merged_schedules = merge_schedules(schedules)
    unresolved_ship_count = sum(1 for issue in issues if issue.kind == "unresolved-ship")
    evidence_count = len(merged_schedules) + unresolved_ship_count
    unresolved_ship_ratio = unresolved_ship_count / evidence_count if evidence_count else 0.0
    status = "partial" if issues else "ok"
    return SourceResult(
        source=SOURCE_ID,
        url=source_url,
        schedules=merged_schedules,
        issues=issues,
        status=status,
        metadata={
            "supportedCapabilities": ["improve"],
            "equipmentEntryCount": equipment_count,
            "shipMapCount": ship_map_count,
            "shipAliasCount": len(ship_refs),
            "unresolvedShipCount": unresolved_ship_count,
            "unresolvedShipRatio": unresolved_ship_ratio,
        },
    )


def collect(item_utils: Start2ItemUtils, ship_utils: Start2ShipUtils) -> SourceResult:
    equipment_catalog = json.loads(fetch(EQUIPMENT_URL, require_fresh=False))
    ship_catalog = json.loads(fetch(SHIP_URL, require_fresh=False))
    return parse_kcwiki_data(equipment_catalog, ship_catalog, item_utils, ship_utils)
