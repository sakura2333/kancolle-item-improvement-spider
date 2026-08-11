from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


# 特殊耗材，勋章这类的。
@dataclass
class ConsumeItem:
    id: int = -2
    count: int = -2
    # weapon 0
    # use_item 1
    type: int = -2

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "count": self.count,
            "type": self.type,
        }

    def __hash__(self):
        return hash((self.id, self.count, self.type))


@dataclass
class TargetWeapon:
    id: int = 0
    level: int = 0
    name: str = ""

    def to_json(self) -> dict:
        result = {
            "id": self.id,
            "level": self.level,
        }
        if self.name:
            result["name"] = self.name
        return result


@dataclass
class ImprovementStage:
    # 升级星数的范围。
    stage_text: str = field(default_factory=str)
    dev_normal: int = -2
    dev_certain: int = -2
    rev_normal: int = -2
    rev_certain: int = -2
    target_weapon: TargetWeapon = field(default_factory=TargetWeapon)
    consumable_list: List["ConsumeItem"] = field(default_factory=list)
    # Internal-only assistant-specific recipes. They are expanded into separate
    # public improvement route records before data is exported.
    route_alternatives: List["ImprovementStageAlternative"] = field(
        default_factory=list,
        repr=False,
    )

    def to_json(self) -> dict:
        return {
            "stageText": self.stage_text,
            "industryResource": [
                self.dev_normal,
                self.dev_certain,
                self.rev_normal,
                self.rev_certain,
            ],
            "targetWeapon": self.target_weapon.to_json(),
            "consumables": [item.to_json() for item in self.consumable_list],
        }


@dataclass
class ImprovementStageAlternative:
    """A full stage recipe selected by an explicit support-ship condition."""

    condition_text: str = ""
    ship_id_list: List[int] = field(default_factory=list)
    stage: ImprovementStage = field(default_factory=ImprovementStage)


@dataclass
class ShipWeek:
    # Legacy anchor IDs retained for backward compatibility.
    id: List[int] = field(default_factory=list)
    text: str = ""
    week: List[int] = field(default_factory=list)
    # Fully expanded result of the Wiki ship selector.
    ship_id_list: List[int] = field(default_factory=list)
    anchor_ship_ids: List[int] = field(default_factory=list)
    parse_status: str = "resolved"
    parse_warnings: List[str] = field(default_factory=list)
    ids_complete: bool = False
    # Original source order keeps list projection order stable after one source
    # rule is split into multiple recipe routes.
    source_order: int = field(default=-1, repr=False)
    # Internal-only specificity information used when Wiki rules overlap.
    match_distance_by_id: Dict[int, int] = field(default_factory=dict, repr=False)

    def to_json(self) -> dict:
        result = {
            "id": self.id,
            "text": self.text,
            "week": self.week,
            "shipIdList": self.ship_id_list,
            "anchorShipIds": self.anchor_ship_ids,
            "parseStatus": self.parse_status,
        }
        if self.ids_complete:
            result["idsComplete"] = True
        if self.parse_warnings:
            result["parseWarnings"] = self.parse_warnings
        return result


@dataclass
class Improvement:
    kind: str = ""
    base_resource: List[int] = field(default_factory=list)
    stage_list: List[ImprovementStage] = field(default_factory=list)
    ship_week_list: List[ShipWeek] = field(default_factory=list)


@dataclass
class WeaponItem:
    tooltip: bool = False
    id: int = field(default=None)
    name: str = field(default_factory=str)  # 包含 ja_jp、zh_cn 等。
    improvement_list: List[Improvement] = field(default_factory=list)
    effect_source: Dict[str, object] = field(default_factory=dict)
    level_expectations: List[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "improvementList": [item.to_json() for item in self.improvement_list],
            "effectSource": self.effect_source,
            "levelExpectations": self.level_expectations,
        }
