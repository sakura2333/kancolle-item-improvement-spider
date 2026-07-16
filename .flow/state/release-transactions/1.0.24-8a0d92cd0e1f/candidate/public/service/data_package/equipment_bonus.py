from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from util.start2.start2_item_utils import Start2ItemUtils
from util.start2.start2_ship_utils import Start2ShipUtils

SOURCE_ID = "kc3-slotitem-bonus"
SOURCE_URL = "https://raw.githubusercontent.com/KC3Kai/kancolle-replay/refs/heads/master/js/data/mst_slotitem_bonus.json"

STAT_NAMES = {
    "houg": "firepower",
    "raig": "torpedo",
    "baku": "bombing",
    "tyku": "antiAir",
    "tais": "asw",
    "houm": "accuracy",
    "kaih": "evasion",
    "souk": "armor",
    "saku": "los",
    "luck": "luck",
    "leng": "range",
}

REQUIREMENT_NAMES = {
    "requiresAR": "airRadar",
    "requiresSR": "surfaceRadar",
    "requiresType": "equipmentTypes",
    "requiresId": "equipmentIds",
}

CONDITION_NAMES = {
    "shipId": "shipIds",
    "shipBase": "shipBaseIds",
    "shipClass": "shipClassIds",
    "shipType": "shipTypeIds",
    "shipCountry": "shipCountries",
    "level": "minImprovement",
    "num": "equipmentCount",
}


@dataclass
class BonusIssue:
    kind: str
    message: str
    equipment_id: Optional[int] = None
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict:
        result = {"source": SOURCE_ID, "kind": self.kind, "message": self.message}
        if self.equipment_id is not None:
            result["equipmentId"] = self.equipment_id
        if self.evidence:
            result["evidence"] = self.evidence
        return result


def _positive_int(value) -> Optional[int]:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _as_int_list(value: Any) -> List[int]:
    values = value if isinstance(value, list) else [value]
    result: List[int] = []
    for current in values:
        number = _positive_int(current)
        if number is not None and number not in result:
            result.append(number)
    return result


def _iter_entries(catalog: Any) -> Iterable[dict]:
    if isinstance(catalog, list):
        yield from (entry for entry in catalog if isinstance(entry, dict))
        return
    if not isinstance(catalog, dict):
        return
    if isinstance(catalog.get("data"), list):
        yield from (entry for entry in catalog["data"] if isinstance(entry, dict))
        return
    if isinstance(catalog.get("bonuses"), list) and any(key in catalog for key in ("ids", "types")):
        yield catalog
        return
    for value in catalog.values():
        if isinstance(value, dict) and (
            "ids" in value or "types" in value or "bonuses" in value
        ):
            yield value
        elif isinstance(value, list):
            yield from (entry for entry in value if isinstance(entry, dict))


def _normalize_bonus(raw_bonus: Any) -> tuple[dict, dict]:
    if not isinstance(raw_bonus, dict):
        return {}, {}
    normalized = {}
    unknown = {}
    for key, value in raw_bonus.items():
        target = STAT_NAMES.get(str(key))
        if target:
            normalized[target] = value
        else:
            unknown[str(key)] = value
    return normalized, unknown


def _normalize_condition(rule: dict) -> dict:
    conditions: Dict[str, Any] = {}
    requires: Dict[str, Any] = {}
    handled = {"bonus"}
    for source_key, target_key in CONDITION_NAMES.items():
        if source_key not in rule:
            continue
        handled.add(source_key)
        value = rule[source_key]
        if target_key.endswith("Ids"):
            conditions[target_key] = _as_int_list(value)
        else:
            conditions[target_key] = value

    for key, value in rule.items():
        if key in handled:
            continue
        if str(key).startswith("requires"):
            target = REQUIREMENT_NAMES.get(str(key), str(key)[8:9].lower() + str(key)[9:])
            requires[target] = value
            handled.add(key)
    if requires:
        conditions["requires"] = requires

    extra = {key: value for key, value in rule.items() if key not in handled}
    if extra:
        conditions["sourceFields"] = extra
    return conditions


def _normalize_rules(
    raw_rules: Any,
    ship_utils: Start2ShipUtils,
    issues: List[BonusIssue],
    equipment_id: Optional[int],
) -> List[dict]:
    if not isinstance(raw_rules, list):
        raw_rules = []

    rules: List[dict] = []
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            continue
        normalized_bonus, unknown_stats = _normalize_bonus(raw_rule.get("bonus"))
        if not normalized_bonus and not unknown_stats:
            issues.append(BonusIssue(
                kind="missing-bonus-value",
                message="bonus rule does not contain stat changes",
                equipment_id=equipment_id,
                evidence={"rule": raw_rule},
            ))
            continue
        conditions = _normalize_condition(raw_rule)
        unknown_ship_ids = [
            ship_id for ship_id in conditions.get("shipIds", [])
            if ship_utils.get_by_id(ship_id) is None
        ]
        if unknown_ship_ids:
            issues.append(BonusIssue(
                kind="unknown-ship-id",
                message="bonus rule contains ship ids not found in start2",
                equipment_id=equipment_id,
                evidence={"shipIds": unknown_ship_ids},
            ))
        rule = {"bonus": normalized_bonus, "conditions": conditions}
        if unknown_stats:
            rule["sourceBonusFields"] = unknown_stats
        rules.append(rule)
    return rules


def parse_special_bonuses(
    catalog: Any,
    item_utils: Start2ItemUtils,
    ship_utils: Start2ShipUtils,
) -> tuple[List[dict], List[BonusIssue], dict]:
    grouped_equipment: Dict[int, List[dict]] = defaultdict(list)
    grouped_types: Dict[Tuple[int, ...], List[dict]] = defaultdict(list)
    issues: List[BonusIssue] = []
    entry_count = 0

    for entry in _iter_entries(catalog):
        entry_count += 1
        equipment_ids = _as_int_list(entry.get("ids") or entry.get("id"))
        equipment_type_ids = _as_int_list(entry.get("types") or entry.get("type"))
        raw_rules = entry.get("bonuses")
        if not isinstance(raw_rules, list):
            raw_rules = [entry.get("bonus")] if isinstance(entry.get("bonus"), dict) else []

        if not equipment_ids and not equipment_type_ids:
            issues.append(BonusIssue(
                kind="missing-bonus-target",
                message="bonus entry does not contain equipment ids or equipment type ids",
                evidence={"entry": entry},
            ))
            continue

        normalized_rules = _normalize_rules(
            raw_rules,
            ship_utils,
            issues,
            equipment_ids[0] if len(equipment_ids) == 1 else None,
        )
        if not normalized_rules:
            continue

        for equipment_id in equipment_ids:
            if item_utils.find_by_id(equipment_id) is None:
                issues.append(BonusIssue(
                    kind="unknown-equipment-id",
                    message="bonus equipment id was not found in start2",
                    equipment_id=equipment_id,
                ))
            grouped_equipment[equipment_id].extend(dict(rule) for rule in normalized_rules)

        if equipment_type_ids:
            grouped_types[tuple(sorted(equipment_type_ids))].extend(
                dict(rule) for rule in normalized_rules
            )

    records: List[dict] = []
    for equipment_id in sorted(grouped_equipment):
        item = item_utils.find_by_id(equipment_id) or {}
        records.append({
            "target": {"kind": "equipment", "equipmentIds": [equipment_id]},
            "equipmentId": equipment_id,
            "equipmentName": str(item.get("api_name") or ""),
            "rules": grouped_equipment[equipment_id],
        })

    for equipment_type_ids in sorted(grouped_types):
        records.append({
            "target": {
                "kind": "equipment-type",
                "equipmentTypeIds": list(equipment_type_ids),
            },
            "equipmentTypeIds": list(equipment_type_ids),
            "rules": grouped_types[equipment_type_ids],
        })

    equipment_rule_count = sum(len(rules) for rules in grouped_equipment.values())
    equipment_type_rule_count = sum(len(rules) for rules in grouped_types.values())
    metadata = {
        "source": SOURCE_ID,
        "sourceUrl": SOURCE_URL,
        "entryCount": entry_count,
        "recordCount": len(records),
        "equipmentRecordCount": len(grouped_equipment),
        "equipmentTypeRecordCount": len(grouped_types),
        "ruleCount": equipment_rule_count + equipment_type_rule_count,
        "equipmentRuleCount": equipment_rule_count,
        "equipmentTypeRuleCount": equipment_type_rule_count,
        "issueCount": len(issues),
        "schemaVersion": 2,
    }
    return records, issues, metadata
