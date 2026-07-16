from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from service.data_package.equipment_drop_from import parse_drop_from
from service.data_package.equipment_sources import (
    build_equipment_source_records,
    write_incremental_source_bundle,
)
from util.start2.start2_item_utils import Start2ItemUtils
from util.start2.start2_ship_utils import Start2ShipUtils


class EquipmentSourcesTest(unittest.TestCase):
    def test_projection_combines_ship_upgrade_and_quest_sources(self):
        items = Start2ItemUtils([
            {"api_id": 1, "api_sortno": 1, "api_name": "起点"},
            {"api_id": 2, "api_sortno": 2, "api_name": "目标"},
            {"api_id": 3, "api_sortno": 3, "api_name": "持参装備"},
        ])
        with tempfile.TemporaryDirectory() as temp_name:
            improvement = Path(temp_name) / "detail.nedb"
            improvement.write_text(json.dumps({
                "id": 1,
                "improvementList": [{
                    "stepList": [{
                        "action": "upgrade",
                        "available": True,
                        "expectedResult": {"targetWeapon": {"id": 2}},
                    }],
                }],
            }) + "\n", encoding="utf-8")
            records, metadata = build_equipment_source_records(
                item_utils=items,
                drop_records=[{
                    "equipmentId": 3,
                    "sources": [{"shipId": 9}],
                }],
                improvement_path=improvement,
                acquisition_records=[{
                    "accepted": True,
                    "equipmentId": 2,
                    "resolvedQuestKeys": [88],
                }],
            )
        by_id = {record["equipmentId"]: record for record in records}
        self.assertEqual(by_id[1]["source"]["upgradeFromItemIds"], [])
        self.assertEqual(by_id[2]["source"]["upgradeFromItemIds"], [1])
        self.assertEqual(by_id[2]["source"]["questKey"], [88])
        self.assertEqual(by_id[3]["source"]["shipIds"], [9])
        self.assertEqual(metadata["equipmentRecordCount"], 3)
        self.assertEqual(metadata["upgradeRelationCount"], 1)

    def test_incremental_bundle_does_not_rewrite_projection_when_unchanged(self):
        records = [{
            "equipmentId": 1,
            "equipmentName": "装備",
            "source": {"shipIds": [], "upgradeFromItemIds": [], "questKey": []},
        }]
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            output = root / "sources.nedb"
            metadata = root / "metadata.json"
            changes = root / "changes.nedb"
            first = write_incremental_source_bundle(
                records=records,
                output_path=output,
                metadata_path=metadata,
                changes_path=changes,
                metadata={"schemaVersion": 1},
                input_hashes={"input": "a"},
            )
            first_mtime = output.stat().st_mtime_ns
            second = write_incremental_source_bundle(
                records=records,
                output_path=output,
                metadata_path=metadata,
                changes_path=changes,
                metadata={"schemaVersion": 1},
                input_hashes={"input": "a"},
            )
            self.assertTrue(first["incremental"]["changed"])
            self.assertFalse(second["incremental"]["changed"])
            self.assertEqual(output.stat().st_mtime_ns, first_mtime)
            self.assertEqual(changes.read_text(encoding="utf-8"), "\n")

    def test_kcwiki_ship_id_is_never_inferred_from_name(self):
        items = Start2ItemUtils([
            {"api_id": 1, "api_sortno": 1, "api_name": "装備"},
        ])
        ships = Start2ShipUtils([
            {"api_id": 9, "api_sortno": 9, "api_name": "吹雪"},
        ])
        records, issues, _ = parse_drop_from(
            {"Fubuki": {"_japanese_name": "吹雪", "_equipment": [{"equipment": "Type A"}]}},
            {"Type A": {"_id": 1}},
            items,
            ships,
        )
        self.assertEqual(records, [])
        self.assertEqual([issue.kind for issue in issues], ["ship-api-id-missing"])

    def test_kcwiki_ship_id_name_conflict_is_rejected(self):
        items = Start2ItemUtils([
            {"api_id": 1, "api_sortno": 1, "api_name": "装備"},
        ])
        ships = Start2ShipUtils([
            {"api_id": 9, "api_sortno": 9, "api_name": "吹雪"},
        ])
        records, issues, _ = parse_drop_from(
            {"Wrong": {"_api_id": 9, "_japanese_name": "白雪", "_equipment": [{"equipment": "Type A"}]}},
            {"Type A": {"_id": 1}},
            items,
            ships,
        )
        self.assertEqual(records, [])
        self.assertEqual([issue.kind for issue in issues], ["ship-api-name-conflict"])


if __name__ == "__main__":
    unittest.main()
