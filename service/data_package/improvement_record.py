from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from service.improvement.model import ImprovementStage, ShipWeek


@dataclass
class ImprovementVO:
    """Canonical public improvement route record."""

    base_resource: List[int] = field(default_factory=list)
    stage_list: List[ImprovementStage] = field(default_factory=list)
    ship_week_list: List[ShipWeek] = field(default_factory=list)
    # Index 0 is all days, indices 1..7 are Sunday..Saturday.
    assistant_ship_ids_by_day: List[Optional[List[int]]] = field(default_factory=list)
    # One public improvement entry is one concrete recipe route. A route can be
    # the normal recipe or an assistant-specific recipe such as 玉波改二.
    route_id: str = ""
    route_type: str = "default"
    route_ship_ids: List[int] = field(default_factory=list)
    route_excluded_ship_ids: List[int] = field(default_factory=list)
    route_source_text: str = ""
    step_list: List[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        result = {
            "baseResource": self.base_resource,
            "stageList": [item.to_json() for item in self.stage_list],
            "shipWeekList": [item.to_json() for item in self.ship_week_list],
            "assistantShipIdsByDay": self.assistant_ship_ids_by_day,
            "routeId": self.route_id,
            "routeType": self.route_type,
            "stepList": self.step_list,
        }
        if self.route_ship_ids:
            result["routeShipIds"] = self.route_ship_ids
        if self.route_excluded_ship_ids:
            result["routeExcludedShipIds"] = self.route_excluded_ship_ids
        if self.route_source_text:
            result["routeSourceText"] = self.route_source_text
        return result


@dataclass
class WeaponItemVO:
    """Canonical public equipment improvement record."""

    tooltip: bool = False
    id: int = field(default=None)
    name: str = field(default_factory=str)  # 包含 ja_jp、zh_cn 等。
    improvement_list: List[ImprovementVO] = field(default_factory=list)
    effect_source: Dict[str, Any] = field(default_factory=dict)
    level_expectations: List[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "improvementList": [item.to_json() for item in self.improvement_list],
            "effectSource": self.effect_source,
            "levelExpectations": self.level_expectations,
        }
