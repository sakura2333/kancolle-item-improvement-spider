from __future__ import annotations

"""Compatibility projections for legacy improvement-data consumers.

The canonical Spider output is schema 4.  ``poi-plugin-item-improvement2``
consumes schema 3 and performs an exact version check, even though the schema-4
change only added fields.  This module keeps a frozen schema-3 value-object
boundary and projects canonical records through explicit field whitelists.
"""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


IMPROVEMENT2_CONSUMER_ID = "poi-plugin-item-improvement2"
IMPROVEMENT2_DETAIL_SCHEMA_VERSION = 3
IMPROVEMENT2_LIST_SCHEMA_VERSION = 2


def _required_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _required_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _required_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    return value


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


def _integer_list(value: Any, label: str) -> tuple[int, ...]:
    return tuple(_required_int(item, f"{label}[]") for item in _required_list(value, label))


def _boolean_list(value: Any, label: str) -> tuple[bool, ...]:
    result: list[bool] = []
    for item in _required_list(value, label):
        if not isinstance(item, bool):
            raise ValueError(f"{label}[] must be a boolean")
        result.append(item)
    return tuple(result)


@dataclass(frozen=True)
class Improvement2ConsumableVO:
    id: int
    count: int
    type: int

    @classmethod
    def from_mapping(cls, value: Any) -> "Improvement2ConsumableVO":
        source = _required_mapping(value, "consumable")
        return cls(
            id=_required_int(source.get("id"), "consumable.id"),
            count=_required_int(source.get("count"), "consumable.count"),
            type=_required_int(source.get("type"), "consumable.type"),
        )

    def to_dict(self) -> dict[str, int]:
        return {"id": self.id, "count": self.count, "type": self.type}


@dataclass(frozen=True)
class Improvement2TargetWeaponVO:
    id: int
    level: int

    @classmethod
    def from_mapping(cls, value: Any) -> "Improvement2TargetWeaponVO":
        source = _required_mapping(value, "targetWeapon")
        return cls(
            id=_required_int(source.get("id"), "targetWeapon.id"),
            level=_required_int(source.get("level"), "targetWeapon.level"),
        )

    def to_dict(self) -> dict[str, int]:
        return {"id": self.id, "level": self.level}


@dataclass(frozen=True)
class Improvement2StageVO:
    stage_text: str
    industry_resource: tuple[int, ...]
    target_weapon: Improvement2TargetWeaponVO
    consumables: tuple[Improvement2ConsumableVO, ...]

    @classmethod
    def from_mapping(cls, value: Any) -> "Improvement2StageVO":
        source = _required_mapping(value, "stage")
        return cls(
            stage_text=_required_string(source.get("stageText"), "stage.stageText"),
            industry_resource=_integer_list(
                source.get("industryResource"), "stage.industryResource"
            ),
            target_weapon=Improvement2TargetWeaponVO.from_mapping(
                source.get("targetWeapon")
            ),
            consumables=tuple(
                Improvement2ConsumableVO.from_mapping(item)
                for item in _required_list(source.get("consumables"), "stage.consumables")
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stageText": self.stage_text,
            "industryResource": list(self.industry_resource),
            "targetWeapon": self.target_weapon.to_dict(),
            "consumables": [item.to_dict() for item in self.consumables],
        }


@dataclass(frozen=True)
class Improvement2ShipWeekVO:
    ids: tuple[int, ...]
    text: str
    week: tuple[bool, ...]
    ship_id_list: tuple[int, ...]
    anchor_ship_ids: tuple[int, ...]
    parse_status: str
    ids_complete: bool | None = None

    @classmethod
    def from_mapping(cls, value: Any) -> "Improvement2ShipWeekVO":
        source = _required_mapping(value, "shipWeek")
        ids_complete = source.get("idsComplete")
        if ids_complete is not None and not isinstance(ids_complete, bool):
            raise ValueError("shipWeek.idsComplete must be a boolean when present")
        return cls(
            ids=_integer_list(source.get("id"), "shipWeek.id"),
            text=_required_string(source.get("text"), "shipWeek.text"),
            week=_boolean_list(source.get("week"), "shipWeek.week"),
            ship_id_list=_integer_list(
                source.get("shipIdList"), "shipWeek.shipIdList"
            ),
            anchor_ship_ids=_integer_list(
                source.get("anchorShipIds"), "shipWeek.anchorShipIds"
            ),
            parse_status=_required_string(
                source.get("parseStatus"), "shipWeek.parseStatus"
            ),
            ids_complete=ids_complete,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": list(self.ids),
            "text": self.text,
            "week": list(self.week),
            "shipIdList": list(self.ship_id_list),
            "anchorShipIds": list(self.anchor_ship_ids),
            "parseStatus": self.parse_status,
        }
        if self.ids_complete is not None:
            result["idsComplete"] = self.ids_complete
        return result


@dataclass(frozen=True)
class Improvement2RouteVO:
    base_resource: tuple[int, ...]
    stage_list: tuple[Improvement2StageVO, ...]
    ship_week_list: tuple[Improvement2ShipWeekVO, ...]
    assistant_ship_ids_by_day: tuple[tuple[int, ...] | None, ...]
    route_id: str
    route_type: str
    route_excluded_ship_ids: tuple[int, ...] | None = None
    route_ship_ids: tuple[int, ...] | None = None
    route_source_text: str | None = None

    @classmethod
    def from_mapping(cls, value: Any) -> "Improvement2RouteVO":
        source = _required_mapping(value, "route")
        by_day: list[tuple[int, ...] | None] = []
        for day in _required_list(
            source.get("assistantShipIdsByDay"), "route.assistantShipIdsByDay"
        ):
            by_day.append(None if day is None else _integer_list(day, "assistantShipIdsByDay[]"))

        route_excluded_ship_ids = source.get("routeExcludedShipIds")
        route_ship_ids = source.get("routeShipIds")
        route_source_text = source.get("routeSourceText")
        if route_source_text is not None and not isinstance(route_source_text, str):
            raise ValueError("route.routeSourceText must be a string when present")

        return cls(
            base_resource=_integer_list(source.get("baseResource"), "route.baseResource"),
            stage_list=tuple(
                Improvement2StageVO.from_mapping(item)
                for item in _required_list(source.get("stageList"), "route.stageList")
            ),
            ship_week_list=tuple(
                Improvement2ShipWeekVO.from_mapping(item)
                for item in _required_list(source.get("shipWeekList"), "route.shipWeekList")
            ),
            assistant_ship_ids_by_day=tuple(by_day),
            route_id=_required_string(source.get("routeId"), "route.routeId"),
            route_type=_required_string(source.get("routeType"), "route.routeType"),
            route_excluded_ship_ids=(
                None
                if route_excluded_ship_ids is None
                else _integer_list(route_excluded_ship_ids, "route.routeExcludedShipIds")
            ),
            route_ship_ids=(
                None
                if route_ship_ids is None
                else _integer_list(route_ship_ids, "route.routeShipIds")
            ),
            route_source_text=route_source_text,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "baseResource": list(self.base_resource),
            "stageList": [item.to_dict() for item in self.stage_list],
            "shipWeekList": [item.to_dict() for item in self.ship_week_list],
            "assistantShipIdsByDay": [
                None if day is None else list(day)
                for day in self.assistant_ship_ids_by_day
            ],
            "routeId": self.route_id,
            "routeType": self.route_type,
        }
        if self.route_excluded_ship_ids is not None:
            result["routeExcludedShipIds"] = list(self.route_excluded_ship_ids)
        if self.route_ship_ids is not None:
            result["routeShipIds"] = list(self.route_ship_ids)
        if self.route_source_text is not None:
            result["routeSourceText"] = self.route_source_text
        return result


@dataclass(frozen=True)
class Improvement2DetailVO:
    id: int
    name: str
    improvement_list: tuple[Improvement2RouteVO, ...]

    @classmethod
    def from_mapping(cls, value: Any) -> "Improvement2DetailVO":
        source = _required_mapping(value, "improvement detail")
        return cls(
            id=_required_int(source.get("id"), "improvement detail.id"),
            name=_required_string(source.get("name"), "improvement detail.name"),
            improvement_list=tuple(
                Improvement2RouteVO.from_mapping(item)
                for item in _required_list(
                    source.get("improvementList"), "improvement detail.improvementList"
                )
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "improvementList": [item.to_dict() for item in self.improvement_list],
        }


def project_improvement2_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Project one canonical schema-4 record into the frozen schema-3 VO."""

    return Improvement2DetailVO.from_mapping(record).to_dict()


def project_improvement2_records(
    records: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [project_improvement2_record(record) for record in records]


def write_improvement2_projection(source: Path, target: Path) -> dict[str, int]:
    target.parent.mkdir(parents=True, exist_ok=True)
    detail_count = 0
    route_count = 0
    with source.open("r", encoding="utf-8") as input_file, target.open(
        "w", encoding="utf-8"
    ) as output_file:
        for line_number, line in enumerate(input_file, start=1):
            if not line.strip():
                continue
            try:
                source_record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid canonical improvement record at line {line_number}: {exc}"
                ) from exc
            projected = project_improvement2_record(source_record)
            detail_count += 1
            route_count += len(projected["improvementList"])
            output_file.write(
                json.dumps(projected, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    return {"detailRecordCount": detail_count, "routeCount": route_count}
