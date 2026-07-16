from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pojo.equip_item import WeaponItemVO
from service.source_validation.model import SourceSchedule, normalize_week
from util.start2.start2_item_utils import Start2ItemUtils
from util.start2.start2_ship_utils import Start2ShipUtils
from util.text_utils import normalize_name

FOOTNOTE_PATTERN = re.compile(r"(?:\[[^\]]*\]|\*\d*|※.*)$")
PRIMARY_PARSER_VERSION = "akashi-route-schema-v3"


def normalize_catalog_name(value: str) -> str:
    value = str(value or "").strip()
    value = value.replace("＋", "+").replace("＆", "&").replace("／", "/")
    value = value.replace("　", " ")
    value = FOOTNOTE_PATTERN.sub("", value).strip()
    return normalize_name(value)


class CatalogMatcher:
    def __init__(self, item_utils: Start2ItemUtils, ship_utils: Start2ShipUtils):
        self.item_utils = item_utils
        self.ship_utils = ship_utils
        self.item_by_name: Dict[str, dict] = {}
        self.ship_by_name: Dict[str, List[dict]] = defaultdict(list)

        for item in item_utils.items:
            name = item.get("api_name") or ""
            if name:
                self.item_by_name[normalize_catalog_name(name)] = item

        for ship in ship_utils.ships:
            name = ship.get("api_name") or ""
            if name:
                self.ship_by_name[normalize_catalog_name(name)].append(ship)

    def item(self, name: str) -> Optional[dict]:
        return self.item_by_name.get(normalize_catalog_name(name))

    def ships(self, name: str) -> List[dict]:
        return list(self.ship_by_name.get(normalize_catalog_name(name), ()))


def merge_schedules(schedules: Iterable[SourceSchedule]) -> List[SourceSchedule]:
    """OR duplicate full facts while preserving route/target distinctions."""
    merged: Dict[Tuple, SourceSchedule] = {}
    order: List[Tuple] = []

    for schedule in schedules:
        key = schedule.identity()
        if key not in merged:
            merged[key] = schedule
            order.append(key)
            continue

        current = merged[key]
        current.week = normalize_week(
            left or right for left, right in zip(current.week, schedule.week)
        )
        refs = current.evidence.setdefault("mergedSourceRefs", [])
        for ref in (current.source_ref, schedule.source_ref):
            if ref and ref not in refs:
                refs.append(ref)

    return [merged[key] for key in order]


def _route_week_by_ship(improvement) -> Dict[Optional[int], List[bool]]:
    by_ship: Dict[Optional[int], List[bool]] = {}
    by_day = list(improvement.assistant_ship_ids_by_day or [])
    for day in range(7):
        day_value = by_day[day + 1] if day + 1 < len(by_day) else None
        if day_value is None:
            continue
        if not day_value:
            by_ship.setdefault(None, [False] * 7)[day] = True
            continue
        for ship_id in day_value:
            by_ship.setdefault(int(ship_id), [False] * 7)[day] = True
    return by_ship


def _route_target_ids(improvement) -> List[int]:
    result: List[int] = []
    for stage in improvement.stage_list:
        target_id = int(getattr(stage.target_weapon, "id", 0) or 0)
        if target_id > 0 and target_id not in result:
            result.append(target_id)
    return result


def _evidence_for_ship(improvement, ship_id: Optional[int]):
    if ship_id is None:
        return "explicit-yes", []
    matching = [
        rule for rule in improvement.ship_week_list
        if ship_id in (getattr(rule, "ship_id_list", []) or [])
    ]
    explicit = any(ship_id in (getattr(rule, "anchor_ship_ids", []) or []) for rule in matching)
    raw_texts = list(dict.fromkeys(rule.text for rule in matching if rule.text))
    return ("explicit-yes" if explicit else "inferred-yes"), raw_texts


def schedules_from_primary(
    items: Sequence[WeaponItemVO],
    ship_utils: Start2ShipUtils,
    source: str = "akashi-list",
) -> List[SourceSchedule]:
    schedules: List[SourceSchedule] = []

    for item in items:
        for route_index, improvement in enumerate(item.improvement_list):
            route_id = improvement.route_id or f"item-{item.id}-route-{route_index}"
            route_signature = route_id
            week_by_ship = _route_week_by_ship(improvement)
            targets = _route_target_ids(improvement)
            route_evidence = {
                "routeType": improvement.route_type,
                "routeShipIds": list(improvement.route_ship_ids),
                "routeExcludedShipIds": list(improvement.route_excluded_ship_ids),
                "routeSourceText": improvement.route_source_text,
                "stageCount": len(improvement.stage_list),
                "stageRecipes": [stage.to_json() for stage in improvement.stage_list],
                "baseResource": list(improvement.base_resource),
            }

            for ship_id, week in week_by_ship.items():
                ship = ship_utils.get_by_id(ship_id) if ship_id is not None else None
                evidence_status, raw_texts = _evidence_for_ship(improvement, ship_id)
                common = dict(
                    source=source,
                    item_id=int(item.id),
                    item_name=item.name,
                    ship_id=ship_id,
                    ship_name=(ship or {}).get("api_name", "-") if ship_id is not None else "-",
                    week=normalize_week(week),
                    route_id=route_id,
                    route_signature=route_signature,
                    evidence_status=evidence_status,
                    parser_version=PRIMARY_PARSER_VERSION,
                    source_ref="generated:improvement-detail",
                    raw_text=" / ".join(raw_texts),
                    evidence=dict(route_evidence),
                )
                schedules.append(SourceSchedule(
                    capability="improve",
                    **common,
                ))
                for target_id in targets:
                    schedules.append(SourceSchedule(
                        capability="upgrade",
                        update_target_item_id=target_id,
                        **common,
                    ))

    return merge_schedules(schedules)
