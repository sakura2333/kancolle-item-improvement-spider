from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from service.data_package.improvement_assistant_reverse import (
    build_assistant_day_reverse_index,
    write_assistant_day_reverse_index,
)


class ImprovementAssistantReverseIndexTest(unittest.TestCase):
    def _write_detail(self, path: Path) -> None:
        records = []
        for equipment_id in range(1, 5):
            records.append({
                "id": equipment_id,
                "name": f"装備{equipment_id}",
                "improvementList": [{
                    "routeId": f"route-{equipment_id}",
                    "routeType": "default",
                    # index 0 is all-day view; 1..7 are Sunday..Saturday.
                    "assistantShipIdsByDay": [[100], [100], None, [], None, None, None, None],
                }],
            })
        # Duplicate route for the same equipment/ship/day should not increase
        # equipmentCount, but should remain as route evidence.
        records[0]["improvementList"].append({
            "routeId": "route-1-alt",
            "routeType": "assistant-specific",
            "assistantShipIdsByDay": [[100], [100], None, None, None, None, None, None],
        })
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")

    def test_builds_day_ship_reverse_index_and_flags_over_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            detail = Path(temp_name) / "detail.nedb"
            self._write_detail(detail)

            payload = build_assistant_day_reverse_index(
                detail,
                threshold=3,
                ship_catalog={100: {"api_id": 100, "api_name": "明石"}},
                generated_at="fixture-time",
            )

        self.assertEqual(payload["recordCount"], 4)
        self.assertEqual(payload["overThresholdShipDayCount"], 1)
        self.assertEqual(payload["maxEquipmentCount"], 4)
        row = payload["overThreshold"][0]
        self.assertEqual(row["dayIndex"], 1)
        self.assertEqual(row["dayName"], "日")
        self.assertEqual(row["shipId"], 100)
        self.assertEqual(row["shipName"], "明石")
        self.assertEqual(row["equipmentCount"], 4)
        first_equipment = row["equipments"][0]
        self.assertEqual(first_equipment["equipmentId"], 1)
        self.assertEqual(
            [route["routeId"] for route in first_equipment["routes"]],
            ["route-1", "route-1-alt"],
        )
        monday = payload["days"][1]
        self.assertEqual(monday["dayIndex"], 2)
        self.assertEqual(monday["ships"], [])

    def test_writes_json_and_markdown_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            detail = root / "detail.nedb"
            self._write_detail(detail)

            metadata = write_assistant_day_reverse_index(detail, root / "report", threshold=3)

            self.assertEqual(metadata["overThresholdShipDayCount"], 1)
            self.assertTrue((root / "report" / "assistant-day-reverse-index.json").is_file())
            markdown = (root / "report" / "assistant-day-reverse-index.md").read_text(encoding="utf-8")
            self.assertIn("ship=100", markdown)
            self.assertIn("equipmentCount=4", markdown)


if __name__ == "__main__":
    unittest.main()
