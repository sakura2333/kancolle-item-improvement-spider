"""Re-run cross-source comparison from the current canonical detail file.

This command intentionally does not regenerate public plugin data.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service.data_package.improvement_record import ImprovementVO, WeaponItemVO
from service.improvement.model import ImprovementStage, ShipWeek
from service.source_validation.runner import run_source_validation
from util.export_utils import get_improvement_db_dir


def _load_detail_as_vo():
    path = Path(get_improvement_db_dir()) / "improvement-detail.nedb"
    items = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            raw = json.loads(line)
            item = WeaponItemVO(id=raw["id"], name=raw.get("name", ""))
            for raw_improvement in raw.get("improvementList", []):
                improvement = ImprovementVO(
                    base_resource=raw_improvement.get("baseResource", []),
                    assistant_ship_ids_by_day=raw_improvement.get("assistantShipIdsByDay", []),
                )
                item.improvement_list.append(improvement)
            items.append(item)
    return items


def compare_current_projection():
    return run_source_validation(_load_detail_as_vo(), record_history=False)


if __name__ == "__main__":
    compare_current_projection()
