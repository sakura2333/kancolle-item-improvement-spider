from __future__ import annotations

from collections import defaultdict
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from service.source_validation.semantic_aliases import resolve_semantic_alias
from util.start2.start2_item_utils import Start2ItemUtils
from util.start2.start2_ship_utils import Start2ShipUtils

SOURCE_ID = "kcwiki-data"
SHIP_URL = "https://raw.githubusercontent.com/kcwiki/kancolle-data/refs/heads/master/wiki/ship.json"
EQUIPMENT_URL = "https://raw.githubusercontent.com/kcwiki/kancolle-data/refs/heads/master/wiki/equipment.json"


@dataclass
class DropFromIssue:
    kind: str
    message: str
    ship_ref: str = ""
    equipment_ref: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict:
        result = {"source": SOURCE_ID, "kind": self.kind, "message": self.message}
        if self.ship_ref:
            result["shipRef"] = self.ship_ref
        if self.equipment_ref:
            result["equipmentRef"] = self.equipment_ref
        if self.evidence:
            result["evidence"] = self.evidence
        return result


def _positive_int(value) -> Optional[int]:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _iter_ship_entries(catalog: Any, path: Tuple[str, ...] = ()):
    if isinstance(catalog, dict):
        if "_equipment" in catalog and ("_api_id" in catalog or "_japanese_name" in catalog):
            yield catalog, path
        for key, value in catalog.items():
            if isinstance(value, (dict, list)):
                yield from _iter_ship_entries(value, path + (str(key),))
    elif isinstance(catalog, list):
        for index, value in enumerate(catalog):
            if isinstance(value, (dict, list)):
                yield from _iter_ship_entries(value, path + (str(index),))


def _equipment_reference_map(catalog: Any) -> Dict[str, int]:
    refs: Dict[str, int] = {}
    entries = catalog.items() if isinstance(catalog, dict) else []
    for key, value in entries:
        if not isinstance(value, dict):
            continue
        item_id = _positive_int(value.get("_id")) or _positive_int(value.get("api_id"))
        if item_id is None:
            continue
        for alias in (key, value.get("_name"), value.get("_japanese_name")):
            if alias:
                refs[str(alias).strip()] = item_id
    return refs


def _normalized_name(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _resolve_ship_id(
    node: dict, ship_utils: Start2ShipUtils
) -> tuple[Optional[int], Optional[str], dict[str, Any]]:
    """Validate KcWiki's API-derived ID; never infer an ID from a name."""
    api_id = _positive_int(node.get("_api_id"))
    kcwiki_name = _normalized_name(node.get("_japanese_name"))
    if api_id is None:
        return None, "ship-api-id-missing", {
            "apiId": node.get("_api_id"),
            "kcwikiName": kcwiki_name,
        }
    ship = ship_utils.get_by_id(api_id)
    if not ship:
        return None, "ship-api-id-not-in-start2", {
            "apiId": api_id,
            "kcwikiName": kcwiki_name,
        }
    start2_name = _normalized_name(ship.get("api_name"))
    if not kcwiki_name or kcwiki_name != start2_name:
        return None, "ship-api-name-conflict", {
            "apiId": api_id,
            "kcwikiName": kcwiki_name,
            "start2Name": start2_name,
        }
    return api_id, None, {
        "apiId": api_id,
        "kcwikiName": kcwiki_name,
        "start2Name": start2_name,
    }


def _resolve_item_id(
    ref: Any,
    reference_map: Dict[str, int],
    item_utils: Start2ItemUtils,
) -> Optional[int]:
    if ref in (None, False, ""):
        return None
    numeric = _positive_int(ref)
    if numeric and item_utils.find_by_id(numeric):
        return numeric
    alias = resolve_semantic_alias(
        SOURCE_ID, "equipment", ref, match_modes={"normalized-alias-exact"}
    )
    if alias is not None and item_utils.find_by_id(alias.canonical_id):
        return alias.canonical_id
    mapped = reference_map.get(str(ref).strip())
    if mapped and item_utils.find_by_id(mapped):
        return mapped
    return None


def parse_drop_from(
    ship_catalog: Any,
    equipment_catalog: Any,
    item_utils: Start2ItemUtils,
    ship_utils: Start2ShipUtils,
) -> tuple[List[dict], List[DropFromIssue], dict]:
    """Convert KcWiki ship loadouts into an equipment -> ship acquisition index.

    Base forms are marked ``initial``. A form with ``_remodel_from`` is marked
    ``remodel`` because its listed loadout is obtained when remodeling into that
    form. The source record is retained so consumers can filter unavailable or
    event-only ships themselves.
    """
    equipment_refs = _equipment_reference_map(equipment_catalog)
    issues: List[DropFromIssue] = []
    grouped: Dict[int, Dict[Tuple[int, str], dict]] = defaultdict(dict)
    ship_entry_count = 0
    relation_count = 0
    semantic_alias_match_count = 0

    for node, path in _iter_ship_entries(ship_catalog):
        ship_entry_count += 1
        ship_id, ship_issue, ship_evidence = _resolve_ship_id(node, ship_utils)
        ship_ref = str(node.get("_japanese_name") or "/".join(path))
        if ship_id is None:
            issues.append(DropFromIssue(
                kind=ship_issue or "unresolved-ship",
                message="KcWiki _api_id failed Start2 ID/name consistency validation",
                ship_ref=ship_ref,
                evidence={"path": list(path), **ship_evidence},
            ))
            continue
        ship = ship_utils.get_by_id(ship_id) or {}
        equipment = node.get("_equipment")
        if not isinstance(equipment, list):
            continue

        method = "remodel" if node.get("_remodel_from") not in (None, False, "") else "initial"
        key_prefix = (ship_id, method)
        for slot_index, slot in enumerate(equipment):
            if not isinstance(slot, dict):
                continue
            equipment_ref = slot.get("equipment")
            if equipment_ref in (None, False, ""):
                continue
            alias = resolve_semantic_alias(
                SOURCE_ID,
                "equipment",
                equipment_ref,
                match_modes={"normalized-alias-exact"},
            )
            item_id = _resolve_item_id(equipment_ref, equipment_refs, item_utils)
            if alias is not None and item_id == alias.canonical_id:
                semantic_alias_match_count += 1
            if item_id is None:
                issues.append(DropFromIssue(
                    kind="unresolved-equipment",
                    message="ship loadout equipment could not be mapped to start2",
                    ship_ref=ship_ref,
                    equipment_ref=str(equipment_ref),
                    evidence={"path": list(path), "slotIndex": slot_index},
                ))
                continue

            relation_count += 1
            entry = grouped[item_id].setdefault(key_prefix, {
                "shipId": ship_id,
                "shipName": str(ship.get("api_name") or ship_ref),
                "method": method,
                "quantity": 0,
                "slotIndices": [],
                "slotSizes": [],
                "sourceShipRef": "/".join(part for part in path if not part.isdigit()),
            })
            entry["quantity"] += 1
            entry["slotIndices"].append(slot_index)
            entry["slotSizes"].append(_positive_int(slot.get("size")) or 0)
            if method == "remodel":
                remodel_level = _positive_int(node.get("_remodel_level"))
                if remodel_level is not None:
                    entry["remodelLevel"] = remodel_level
                entry["remodelFrom"] = node.get("_remodel_from")
            availability = node.get("_availability")
            if isinstance(availability, list) and availability:
                entry["shipAvailability"] = availability

    records: List[dict] = []
    for item_id in sorted(grouped):
        item = item_utils.find_by_id(item_id) or {}
        sources = sorted(
            grouped[item_id].values(),
            key=lambda value: (value["shipId"], value["method"], value["slotIndices"]),
        )
        records.append({
            "equipmentId": item_id,
            "equipmentName": str(item.get("api_name") or ""),
            "sources": sources,
        })

    metadata = {
        "source": SOURCE_ID,
        "sourceUrls": [SHIP_URL, EQUIPMENT_URL],
        "shipEntryCount": ship_entry_count,
        "equipmentRecordCount": len(records),
        "relationCount": relation_count,
        "issueCount": len(issues),
        "semanticAliasMatchCount": semantic_alias_match_count,
        "schemaVersion": 1,
    }
    return records, issues, metadata
