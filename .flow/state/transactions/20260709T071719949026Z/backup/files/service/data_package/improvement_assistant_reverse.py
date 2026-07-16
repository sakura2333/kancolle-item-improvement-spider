from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from util.start2.start2_ship_utils import ship_utils

DAY_DEFINITIONS = (
    (1, "sunday", "日"),
    (2, "monday", "月"),
    (3, "tuesday", "火"),
    (4, "wednesday", "水"),
    (5, "thursday", "木"),
    (6, "friday", "金"),
    (7, "saturday", "土"),
)

DEFAULT_THRESHOLD = 3


def _read_nedb(path: Path) -> Iterable[dict[str, Any]]:
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at {path}:{line_number}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"invalid record at {path}:{line_number}: expected object")
        yield row


def _ship_name(ship_id: int, ship_catalog: Mapping[int, Mapping[str, Any]]) -> str:
    ship = ship_catalog.get(ship_id)
    if not isinstance(ship, Mapping):
        return ""
    return str(ship.get("api_name") or ship.get("api_name_jp") or ship.get("api_yomi") or "")


def _load_ship_catalog() -> dict[int, Mapping[str, Any]]:
    catalog = ship_utils.load()
    ships = getattr(catalog, "ships", []) or []
    result: dict[int, Mapping[str, Any]] = {}
    for ship in ships:
        if not isinstance(ship, Mapping):
            continue
        try:
            ship_id = int(ship.get("api_id"))
        except (TypeError, ValueError):
            continue
        result[ship_id] = ship
    return result


def _route_summary(route: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "routeId": str(route.get("routeId") or ""),
        "routeType": str(route.get("routeType") or "default"),
        "routeSourceText": str(route.get("routeSourceText") or ""),
    }


def _assistant_ids_for_day(route: Mapping[str, Any], day_index: int) -> list[int] | None:
    by_day = route.get("assistantShipIdsByDay")
    if not isinstance(by_day, list) or len(by_day) <= day_index:
        return None
    value = by_day[day_index]
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    result: list[int] = []
    for raw_id in value:
        try:
            ship_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if ship_id > 0 and ship_id not in result:
            result.append(ship_id)
    return result


def build_assistant_day_reverse_index(
    detail_path: Path,
    *,
    threshold: int = DEFAULT_THRESHOLD,
    ship_catalog: Mapping[int, Mapping[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build day -> assistant ship -> improveable equipment reverse diagnostics.

    The source of truth is the already-normalized canonical improvement detail.
    Index 0 in ``assistantShipIdsByDay`` is the all-day view, while indices 1..7
    are Sunday..Saturday.  The reverse index intentionally counts unique
    equipment IDs per ship per concrete day; multiple routes for the same
    equipment/ship/day are retained as route evidence but counted once.
    """

    if threshold < 0:
        raise ValueError("threshold must be non-negative")
    ships = dict(ship_catalog) if ship_catalog is not None else _load_ship_catalog()
    by_day_ship: dict[int, dict[int, dict[int, dict[str, Any]]]] = {
        day_index: defaultdict(dict) for day_index, _, _ in DAY_DEFINITIONS
    }

    record_count = 0
    route_count = 0
    evidence_count = 0
    for record in _read_nedb(detail_path):
        record_count += 1
        try:
            equipment_id = int(record.get("id"))
        except (TypeError, ValueError):
            continue
        equipment_name = str(record.get("name") or "")
        routes = record.get("improvementList")
        if not isinstance(routes, list):
            continue
        for route in routes:
            if not isinstance(route, Mapping):
                continue
            route_count += 1
            route_info = _route_summary(route)
            for day_index, _day_key, _day_name in DAY_DEFINITIONS:
                ship_ids = _assistant_ids_for_day(route, day_index)
                if not ship_ids:
                    continue
                for ship_id in ship_ids:
                    equipment_map = by_day_ship[day_index][ship_id]
                    entry = equipment_map.setdefault(equipment_id, {
                        "equipmentId": equipment_id,
                        "equipmentName": equipment_name,
                        "routes": [],
                    })
                    route_key = (
                        route_info["routeId"],
                        route_info["routeType"],
                        route_info["routeSourceText"],
                    )
                    existing_keys = {
                        (item.get("routeId"), item.get("routeType"), item.get("routeSourceText"))
                        for item in entry["routes"]
                    }
                    if route_key not in existing_keys:
                        entry["routes"].append(route_info)
                        evidence_count += 1

    days = []
    over_threshold = []
    max_equipment_count = 0
    for day_index, day_key, day_name in DAY_DEFINITIONS:
        ships_for_day = []
        for ship_id in sorted(by_day_ship[day_index]):
            equipment_entries = sorted(
                by_day_ship[day_index][ship_id].values(),
                key=lambda item: (int(item["equipmentId"]), str(item["equipmentName"])),
            )
            equipment_count = len(equipment_entries)
            max_equipment_count = max(max_equipment_count, equipment_count)
            row = {
                "dayIndex": day_index,
                "dayKey": day_key,
                "dayName": day_name,
                "shipId": ship_id,
                "shipName": _ship_name(ship_id, ships),
                "equipmentCount": equipment_count,
                "equipments": equipment_entries,
            }
            ships_for_day.append(row)
            if equipment_count > threshold:
                over_threshold.append(row)
        days.append({
            "dayIndex": day_index,
            "dayKey": day_key,
            "dayName": day_name,
            "shipCount": len(ships_for_day),
            "ships": ships_for_day,
        })

    over_threshold = sorted(
        over_threshold,
        key=lambda item: (
            int(item["dayIndex"]),
            -int(item["equipmentCount"]),
            int(item["shipId"]),
        ),
    )
    return {
        "schemaVersion": 1,
        "source": "akashi-list-canonical-improvement-detail",
        "status": "passed",
        "generatedAt": generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "threshold": threshold,
        "dayIndexBase": "1..7 = Sunday..Saturday; 0 is all-day view and is intentionally excluded",
        "recordCount": record_count,
        "routeCount": route_count,
        "evidenceCount": evidence_count,
        "shipDayCount": sum(len(day["ships"]) for day in days),
        "overThresholdShipDayCount": len(over_threshold),
        "maxEquipmentCount": max_equipment_count,
        "overThreshold": over_threshold,
        "days": days,
    }


def write_assistant_day_reverse_index(
    detail_path: Path,
    output_dir: Path,
    *,
    threshold: int = DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    payload = build_assistant_day_reverse_index(detail_path, threshold=threshold)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "assistant-day-reverse-index.json"
    md_path = output_dir / "assistant-day-reverse-index.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    return {
        "schemaVersion": payload["schemaVersion"],
        "path": str(json_path.name),
        "markdown": str(md_path.name),
        "threshold": payload["threshold"],
        "overThresholdShipDayCount": payload["overThresholdShipDayCount"],
        "maxEquipmentCount": payload["maxEquipmentCount"],
        "shipDayCount": payload["shipDayCount"],
    }


def _equipment_text(equipment: Mapping[str, Any], *, limit_routes: int = 2) -> str:
    routes = equipment.get("routes") if isinstance(equipment.get("routes"), list) else []
    route_text = ""
    route_ids = [str(route.get("routeId") or "") for route in routes if isinstance(route, Mapping)]
    route_ids = [route_id for route_id in route_ids if route_id]
    if route_ids:
        route_text = " routes=" + ",".join(route_ids[:limit_routes])
        if len(route_ids) > limit_routes:
            route_text += f"(+{len(route_ids) - limit_routes})"
    return f"{equipment.get('equipmentId')}:{equipment.get('equipmentName')}{route_text}"


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Improvement assistant day reverse index",
        "",
        f"generatedAt: {payload.get('generatedAt')}",
        f"threshold: > {payload.get('threshold')} equipments per ship per day",
        f"recordCount: {payload.get('recordCount')}",
        f"routeCount: {payload.get('routeCount')}",
        f"shipDayCount: {payload.get('shipDayCount')}",
        f"overThresholdShipDayCount: {payload.get('overThresholdShipDayCount')}",
        f"maxEquipmentCount: {payload.get('maxEquipmentCount')}",
        "",
        "## Over threshold",
        "",
    ]
    over = payload.get("overThreshold") if isinstance(payload.get("overThreshold"), list) else []
    if not over:
        lines.append("No ship/day has more than the threshold equipment count.")
    else:
        for row in over:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                f"- day={row.get('dayName')}({row.get('dayIndex')}) "
                f"ship={row.get('shipId')}:{row.get('shipName')} "
                f"equipmentCount={row.get('equipmentCount')}"
            )
            equipments = row.get("equipments") if isinstance(row.get("equipments"), list) else []
            for equipment in equipments:
                if isinstance(equipment, Mapping):
                    lines.append(f"  - {_equipment_text(equipment)}")
    lines.append("")
    lines.append("## Full reverse table")
    lines.append("")
    days = payload.get("days") if isinstance(payload.get("days"), list) else []
    for day in days:
        if not isinstance(day, Mapping):
            continue
        lines.append(f"### {day.get('dayName')} ({day.get('dayKey')})")
        ships = day.get("ships") if isinstance(day.get("ships"), list) else []
        if not ships:
            lines.append("")
            lines.append("No named assistant ship routes.")
            lines.append("")
            continue
        for row in ships:
            if not isinstance(row, Mapping):
                continue
            equipment_ids = [
                str(equipment.get("equipmentId"))
                for equipment in row.get("equipments", [])
                if isinstance(equipment, Mapping)
            ]
            lines.append(
                f"- ship={row.get('shipId')}:{row.get('shipName')} "
                f"equipmentCount={row.get('equipmentCount')} "
                f"equipmentIds={','.join(equipment_ids)}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
