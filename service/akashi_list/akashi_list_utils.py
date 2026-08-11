from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from service.data_package.improvement_record import ImprovementVO, WeaponItemVO
from service.improvement.model import ConsumeItem, Improvement, ImprovementStage, ShipWeek, WeaponItem
from service.akashi_list.improvement_expectation import build_route_step_list
from util.logger import simple_logger
from util.start2.start2_item_utils import start2ItemUtils
from util.start2.start2_ship_utils import ship_utils
from util.start2.start2_use_item_utils import start2ConsumeUseUtils
from util.text_utils import normalize_name


def require_record(record, kind: str, name: str):
    if record is None:
        simple_logger.error(f"[start2 missing] {kind}: {name}")
        assert False
    return record


def search_title(current_node):
    return current_node.xpath(".//*[@title]")


def query_consumable(item_name):
    item = ConsumeItem()
    record = start2ItemUtils.find_by_name_normalized(normalize_name(item_name))
    item.type = 0

    if record is None:
        record = start2ConsumeUseUtils.find_by_name(name=item_name)
        item.type = 1
    if record is None:
        return None
    item.id = record.get("api_id")
    return item


def extract_name_and_count(text: str) -> Tuple[str, int]:
    if "二番艦" in text:
        simple_logger.info(f"[route] conditional stage recipe: {text}")
        text = text.split("二番艦")[0]
    groups = re.match(r"^(.+?)(\s*×\s*)?(\d+)?$", text.strip()).groups()
    return groups[0].strip(), 0 if groups[2] is None else int(groups[2])


def extract_weapon_name(text: str) -> str:
    text = normalize_name(text)
    m = re.search(r'^(\d+:\s*)?(.+)?$', text)
    return m.groups()[1].strip() if m else ''


def _consumable_signature(consumables: Iterable[ConsumeItem]):
    return tuple((int(c.id), int(c.count), int(c.type)) for c in consumables)


def stage_signature(stage_list):
    """A complete recipe signature.

    The old implementation only compared stage text and consumables, which could
    merge routes with different costs or different MAX upgrade targets.
    """
    return tuple(
        (
            s.stage_text,
            int(s.dev_normal),
            int(s.dev_certain),
            int(s.rev_normal),
            int(s.rev_certain),
            int(s.target_weapon.id),
            int(s.target_weapon.level),
            _consumable_signature(s.consumable_list),
        )
        for s in stage_list
    )


def _clean_stage(stage: ImprovementStage) -> ImprovementStage:
    result = copy.deepcopy(stage)
    result.route_alternatives = []
    return result


def _copy_ship_week(rule: ShipWeek, ship_ids: List[int], *, ids_complete: bool = False) -> ShipWeek:
    anchors = [ship_id for ship_id in rule.anchor_ship_ids if ship_id in ship_ids]
    distances = {
        int(ship_id): int(distance)
        for ship_id, distance in (rule.match_distance_by_id or {}).items()
        if int(ship_id) in ship_ids
    }
    return ShipWeek(
        id=[ship_ids[0]] if ship_ids else [0],
        text=rule.text,
        week=list(rule.week),
        ship_id_list=list(ship_ids),
        anchor_ship_ids=anchors,
        parse_status=rule.parse_status,
        parse_warnings=list(rule.parse_warnings),
        ids_complete=ids_complete or rule.ids_complete,
        source_order=rule.source_order,
        match_distance_by_id=distances,
    )


def _default_route_rules(rules: List[ShipWeek], excluded_ship_ids: set[int]) -> List[ShipWeek]:
    result: List[ShipWeek] = []
    for rule in rules:
        ids = list(rule.ship_id_list or [])
        if not ids:
            # Keep the "no named assistant" route only in the default recipe.
            result.append(copy.deepcopy(rule))
            continue
        filtered = [ship_id for ship_id in ids if ship_id not in excluded_ship_ids]
        if filtered:
            result.append(_copy_ship_week(rule, filtered))
    return result


def _projection_week_for_ship(projection, ship_id: int) -> List[bool]:
    return [
        isinstance(projection[day + 1], list) and ship_id in projection[day + 1]
        for day in range(7)
    ]


def _special_route_rules(
    condition_text: str,
    route_ship_ids: List[int],
    base_projection,
    source_rules: List[ShipWeek],
) -> List[ShipWeek]:
    loaded_ships = ship_utils.load()
    result: List[ShipWeek] = []
    for ship_id in route_ship_ids:
        week = _projection_week_for_ship(base_projection, ship_id)
        if not any(week):
            continue
        ship = loaded_ships.get_by_id(ship_id) or {}
        explicit_orders = [
            rule.source_order for rule in source_rules
            if ship_id in (rule.anchor_ship_ids or []) and rule.source_order >= 0
        ]
        covering_orders = [
            rule.source_order for rule in source_rules
            if ship_id in (rule.ship_id_list or []) and rule.source_order >= 0
        ]
        source_order = min(explicit_orders or covering_orders or [-1])
        result.append(ShipWeek(
            id=[ship_id],
            text=str(ship.get("api_name") or condition_text or f"#{ship_id}"),
            week=week,
            ship_id_list=[ship_id],
            anchor_ship_ids=[ship_id],
            parse_status="resolved",
            ids_complete=True,
            source_order=source_order,
            match_distance_by_id={ship_id: 0},
        ))
    return result


def _route_id(route_type: str, ship_ids: Iterable[int], stages: List[ImprovementStage]) -> str:
    payload = {
        "type": route_type,
        "shipIds": list(ship_ids),
        "stages": stage_signature(stages),
    }
    digest = hashlib.sha1(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=list).encode("utf-8")
    ).hexdigest()[:12]
    suffix = "-".join(str(value) for value in ship_ids) or "all"
    return f"{route_type}:{suffix}:{digest}"


def _alternative_groups(stages: List[ImprovementStage]):
    groups: Dict[Tuple[int, ...], dict] = {}
    owner_by_ship: Dict[int, Tuple[int, ...]] = {}
    for stage_index, stage in enumerate(stages):
        for alternative in stage.route_alternatives:
            key = tuple(dict.fromkeys(int(ship_id) for ship_id in alternative.ship_id_list))
            if not key:
                continue
            for ship_id in key:
                previous = owner_by_ship.get(ship_id)
                if previous is not None and previous != key:
                    raise ValueError(
                        f"overlapping assistant-specific recipes for ship {ship_id}: {previous} vs {key}"
                    )
                owner_by_ship[ship_id] = key
            group = groups.setdefault(key, {
                "conditionText": alternative.condition_text,
                "replacements": {},
            })
            group["replacements"][stage_index] = _clean_stage(alternative.stage)
    return groups


def _expand_improvement_routes(improvement: Improvement) -> List[ImprovementVO]:
    groups = _alternative_groups(improvement.stage_list)
    if not groups:
        stages = [_clean_stage(stage) for stage in improvement.stage_list]
        return [ImprovementVO(
            base_resource=list(improvement.base_resource),
            stage_list=stages,
            ship_week_list=copy.deepcopy(improvement.ship_week_list),
            route_id=_route_id("default", (), stages),
            route_type="default",
            step_list=build_route_step_list(stages),
        )]

    base_projection = build_assistant_ship_ids_by_day(improvement.ship_week_list)
    special_ids = {ship_id for key in groups for ship_id in key}
    routes: List[ImprovementVO] = []

    default_stages = [_clean_stage(stage) for stage in improvement.stage_list]
    default_rules = _default_route_rules(improvement.ship_week_list, special_ids)
    if default_rules:
        routes.append(ImprovementVO(
            base_resource=list(improvement.base_resource),
            stage_list=default_stages,
            ship_week_list=default_rules,
            route_id=_route_id("default", (), default_stages),
            route_type="default",
            route_excluded_ship_ids=sorted(special_ids),
            step_list=build_route_step_list(default_stages),
        ))

    for key, group in groups.items():
        route_ship_ids = list(key)
        stages = []
        for stage_index, base_stage in enumerate(improvement.stage_list):
            stages.append(copy.deepcopy(
                group["replacements"].get(stage_index, _clean_stage(base_stage))
            ))
        rules = _special_route_rules(
            group["conditionText"],
            route_ship_ids,
            base_projection,
            improvement.ship_week_list,
        )
        if not rules:
            simple_logger.warning(
                f"[route] assistant-specific recipe has no available schedule: {group['conditionText']}"
            )
            continue
        routes.append(ImprovementVO(
            base_resource=list(improvement.base_resource),
            stage_list=stages,
            ship_week_list=rules,
            route_id=_route_id("assistant-specific", route_ship_ids, stages),
            route_type="assistant-specific",
            route_ship_ids=route_ship_ids,
            route_source_text=group["conditionText"],
            step_list=build_route_step_list(stages),
        ))

    return routes


def convert_vo(items: list[WeaponItem]) -> list[WeaponItemVO]:
    vo_list = []
    for item in items:
        vo = WeaponItemVO()
        vo.id = item.id
        vo.name = item.name
        vo.tooltip = item.tooltip
        vo.improvement_list = build_improvement_vo_list(item.improvement_list)
        vo.effect_source = copy.deepcopy(item.effect_source)
        vo.level_expectations = copy.deepcopy(item.level_expectations)
        vo_list.append(vo)
    return vo_list


def _merge_route_vo(target: ImprovementVO, incoming: ImprovementVO):
    target.ship_week_list.extend(copy.deepcopy(incoming.ship_week_list))
    target.route_ship_ids = list(dict.fromkeys(target.route_ship_ids + incoming.route_ship_ids))
    target.route_excluded_ship_ids = list(dict.fromkeys(
        target.route_excluded_ship_ids + incoming.route_excluded_ship_ids
    ))
    if not target.route_source_text:
        target.route_source_text = incoming.route_source_text


def build_improvement_vo_list(improvements: list[Improvement]) -> list[ImprovementVO]:
    result_dic = {}
    for improvement in improvements:
        for route in _expand_improvement_routes(improvement):
            key = (
                tuple(route.base_resource),
                stage_signature(route.stage_list),
                route.route_type,
                tuple(route.route_ship_ids),
                tuple(route.route_excluded_ship_ids),
            )
            if key not in result_dic:
                result_dic[key] = route
            else:
                _merge_route_vo(result_dic[key], route)

    result = list(result_dic.values())
    final: List[ImprovementVO] = []
    for improvement_vo in result:
        improvement_vo.assistant_ship_ids_by_day = build_assistant_ship_ids_by_day(
            improvement_vo.ship_week_list
        )
        if any(value is not None for value in improvement_vo.assistant_ship_ids_by_day[1:]):
            final.append(improvement_vo)
    return final


def build_assistant_ship_ids_by_day(ship_week_list: list):
    """Resolve overlapping Wiki rules into all + Sunday..Saturday ID projections.

    Each entry has three states:
    - None: this improvement route is unavailable on the view day.
    - []: available without a named support ship.
    - [ids...]: available with normalized support ships.

    A more specific rule (its anchor is closer to the concrete ship) overrides an
    ancestor rule even when that day is disabled. Rules with equal specificity are
    merged with OR semantics.
    """
    ordered_ship_ids = []
    for ship_week in ship_week_list:
        for ship_id in getattr(ship_week, "ship_id_list", []) or []:
            if ship_id not in ordered_ship_ids:
                ordered_ship_ids.append(ship_id)

    available_by_weekday = [
        any(bool((rule.week or [False] * 7)[day]) for rule in ship_week_list)
        for day in range(7)
    ]
    weekdays = [[] if available else None for available in available_by_weekday]

    for ship_id in ordered_ship_ids:
        covering_rules = [
            ship_week for ship_week in ship_week_list
            if ship_id in (getattr(ship_week, "ship_id_list", []) or [])
        ]
        if not covering_rules:
            continue

        def distance(rule):
            return (getattr(rule, "match_distance_by_id", {}) or {}).get(ship_id, 10 ** 9)

        best_distance = min(distance(rule) for rule in covering_rules)
        best_rules = [rule for rule in covering_rules if distance(rule) == best_distance]

        for day in range(7):
            if weekdays[day] is not None and any(
                bool((rule.week or [False] * 7)[day]) for rule in best_rules
            ):
                weekdays[day].append(ship_id)

    all_days = [
        ship_id for ship_id in ordered_ship_ids
        if any(day_ids is not None and ship_id in day_ids for day_ids in weekdays)
    ]
    all_view = all_days if any(available_by_weekday) else None
    return [all_view] + weekdays
