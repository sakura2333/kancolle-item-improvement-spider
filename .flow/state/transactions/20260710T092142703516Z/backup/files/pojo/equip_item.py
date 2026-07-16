from dataclasses import dataclass, field
from typing import Any, Dict, List

from pojo.improvement import Improvement, ImprovementVO


@dataclass
class WeaponItemVO:
    tooltip: bool = False
    id: int = field(default=None)
    name: str  = field(default_factory=str)# 包含 ja_jp, zh_cn 等
    # 核心嵌套数据
    improvement_list: List[ImprovementVO] = field(default_factory=list)
    effect_source: Dict[str, Any] = field(default_factory=dict)
    level_expectations: List[dict] = field(default_factory=list)

    def to_json(self):
        return {
            'id' : self.id,
            'name' : self.name,
            'improvementList' :  [c.to_json() for c in self.improvement_list],
            'effectSource': self.effect_source,
            'levelExpectations': self.level_expectations,
        }



@dataclass
class WeaponItem:
    tooltip: bool = False
    id: int = field(default=None)
    name: str  = field(default_factory=str)# 包含 ja_jp, zh_cn 等
    # 核心嵌套数据
    improvement_list: List[Improvement] = field(default_factory=list)
    effect_source: Dict[str, Any] = field(default_factory=dict)
    level_expectations: List[dict] = field(default_factory=list)

    def to_json(self):
        return {
            'id' : self.id,
            'name' : self.name,
            'improvementList' :  [c.to_json() for c in self.improvement_list],
            'effectSource': self.effect_source,
            'levelExpectations': self.level_expectations,
        }
