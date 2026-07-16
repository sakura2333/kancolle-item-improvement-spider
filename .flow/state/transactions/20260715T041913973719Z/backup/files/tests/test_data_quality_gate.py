import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from service.data_package.improvement_compat import project_improvement2_record
from service.data_package.quality_gate import (
    QualityGateError,
    inspect_package,
    validate_against_baseline,
)


class DataQualityGateTest(unittest.TestCase):
    @staticmethod
    def _fresh_fetch(url: str) -> dict:
        return {
            "url": url,
            "status": "fresh",
            "validatedInRun": True,
            "usedCacheFallback": False,
        }

    def _write_package(self, root: Path, item_count: int = 3):
        (root / "improvement").mkdir(parents=True, exist_ok=True)
        (root / "equipment").mkdir(parents=True, exist_ok=True)
        (root / "assets" / "useitem").mkdir(parents=True, exist_ok=True)
        (root / "assets" / "equip").mkdir(parents=True, exist_ok=True)
        compatibility_root = root / "compat" / "poi-plugin-item-improvement2"
        (compatibility_root / "improvement").mkdir(parents=True, exist_ok=True)
        (compatibility_root / "assets" / "useitem").mkdir(parents=True, exist_ok=True)
        manifest = {
            "datasets": {
                "improvement": {
                    "schemaVersion": 4,
                    "status": "ok",
                    "collectionCompletedInRun": True,
                    "fetches": [self._fresh_fetch("fixture://akashi")],
                },
                "equipmentDropFrom": {
                    "schemaVersion": 1,
                    "status": "ok",
                    "fetches": [self._fresh_fetch("fixture://drop")],
                },
                "equipmentSources": {
                    "schemaVersion": 1,
                    "status": "ok",
                },
                "equipmentSpecialBonuses": {
                    "schemaVersion": 2,
                    "status": "ok",
                    "fetches": [self._fresh_fetch("fixture://bonus")],
                },
                "useitemIcons": {
                    "schemaVersion": 2,
                    "directory": "assets/useitem",
                    "format": "webp",
                    "quality": 93,
                    "source": "official-useitem-card",
                    "requiredIds": [1],
                    "availableIds": [1],
                    "missingIds": [],
                },
                "equipmentImages": {
                    "schemaVersion": 2,
                    "directory": "assets/equip",
                    "format": "webp",
                    "quality": 93,
                    "source": "official-slot-card",
                    "availableIds": [],
                },
            },
            "compatibility": {
                "poiPluginItemImprovement2": {
                    "consumer": "poi-plugin-item-improvement2",
                    "manifest": "compat/poi-plugin-item-improvement2/manifest.json",
                    "detail": "compat/poi-plugin-item-improvement2/improvement/detail.nedb",
                    "list": "compat/poi-plugin-item-improvement2/improvement/list.json",
                    "schemaVersion": 3,
                    "listSchemaVersion": 2,
                    "detailRecordCount": item_count,
                    "routeCount": item_count,
                }
            },
        }
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        rows = [[item_id, [f"ship-{item_id}"]] for item_id in range(1, item_count + 1)]
        list_document = {
            "metadata": {
                "schemaVersion": 2,
                "rowSchema": ["itemId", "assistantTexts"],
                "itemCount": item_count,
            },
            "data": [rows for _ in range(8)],
        }
        list_payload = json.dumps(list_document, ensure_ascii=False)
        (root / "improvement" / "list.json").write_text(
            list_payload, encoding="utf-8"
        )
        (compatibility_root / "improvement" / "list.json").write_text(
            list_payload, encoding="utf-8"
        )
        steps = [
            {
                "fromLevel": level,
                "fromLabel": "★MAX" if level == 10 else f"★{level}",
                "action": "upgrade" if level == 10 else "improve",
                "available": False if level == 10 else True,
                **({
                    "expectedResult": {
                        "kind": "level",
                        "level": level + 1,
                        "label": "★MAX" if level == 9 else f"★{level + 1}",
                    },
                    "effectExpectationLevel": level + 1,
                    "sourceStageText": "★0~★5" if level <= 5 else "★6~★9",
                    "industryResource": [1, 2, 3, 4],
                    "consumables": [{"id": 1, "count": 1, "type": 1}],
                } if level < 10 else {}),
            }
            for level in range(11)
        ]
        details = [
            {
                "id": item_id,
                "name": f"equipment-{item_id}",
                "effectSource": {"status": "ok", "source": "fixture"},
                "levelExpectations": [
                    {
                        "level": level,
                        "label": "★MAX" if level == 10 else f"★{level}",
                        "effects": [] if level == 0 else [{
                            "name": "火力",
                            "valueText": f"+{level}",
                            "value": float(level),
                            "sourceRow": 2,
                        }],
                    }
                    for level in range(11)
                ],
                "improvementList": [{
                    "baseResource": [1, 2, 3, 4],
                    "stageList": [{
                        "stageText": "★0~★5",
                        "industryResource": [1, 2, 3, 4],
                        "targetWeapon": {"id": 1, "level": 0},
                        "consumables": [{"id": 1, "count": 1, "type": 1}],
                    }],
                    "shipWeekList": [{
                        "id": [1],
                        "text": "ship-1",
                        "week": [True, True, True, True, True, True, True],
                        "shipIdList": [1],
                        "anchorShipIds": [1],
                        "parseStatus": "resolved",
                        "idsComplete": True,
                    }],
                    "assistantShipIdsByDay": [[1], [1], [1], [1], [1], [1], [1]],
                    "routeId": f"route-{item_id}",
                    "routeType": "default",
                    "routeShipIds": [1],
                    "routeSourceText": "fixture",
                    "stepList": steps,
                }],
            }
            for item_id in range(1, item_count + 1)
        ]
        (root / "improvement" / "detail.nedb").write_text(
            "".join(json.dumps(record) + "\n" for record in details), encoding="utf-8"
        )
        compatibility_details = [project_improvement2_record(record) for record in details]
        (compatibility_root / "improvement" / "detail.nedb").write_text(
            "".join(json.dumps(record) + "\n" for record in compatibility_details),
            encoding="utf-8",
        )
        compatibility_manifest = {
            "consumer": "poi-plugin-item-improvement2",
            "datasets": {
                "improvement": {
                    "schemaVersion": 3,
                    "listSchemaVersion": 2,
                    "detail": "improvement/detail.nedb",
                    "list": "improvement/list.json",
                    "detailRecordCount": item_count,
                    "routeCount": item_count,
                },
                "useitemIcons": {
                    "schemaVersion": 1,
                    "directory": "assets/useitem",
                    "format": "png",
                    "source": "official-useitem-card",
                    "requiredIds": [1],
                    "availableIds": [1],
                    "missingIds": [],
                },
            },
        }
        (compatibility_root / "manifest.json").write_text(
            json.dumps(compatibility_manifest), encoding="utf-8"
        )
        drop_from = {
            "equipmentId": 1,
            "equipmentName": "equipment-1",
            "sources": [{
                "shipId": 1,
                "shipName": "ship-1",
                "method": "initial",
                "quantity": 2,
            }],
        }
        (root / "equipment" / "drop-from.nedb").write_text(
            json.dumps(drop_from) + "\n", encoding="utf-8"
        )
        equipment_sources = [
            {
                "equipmentId": item_id,
                "equipmentName": f"equipment-{item_id}",
                "source": {
                    "shipIds": [1] if item_id == 1 else [],
                    "upgradeFromItemIds": [],
                    "questKey": [],
                },
            }
            for item_id in range(1, item_count + 1)
        ]
        (root / "equipment" / "sources.nedb").write_text(
            "".join(json.dumps(record) + "\n" for record in equipment_sources),
            encoding="utf-8",
        )
        bonuses = [
            {
                "target": {"kind": "equipment", "equipmentIds": [1]},
                "equipmentId": 1,
                "equipmentName": "equipment-1",
                "rules": [{"bonus": {"firepower": 1}, "conditions": {}}],
            },
            {
                "target": {"kind": "equipment-type", "equipmentTypeIds": [9]},
                "equipmentTypeIds": [9],
                "rules": [{"bonus": {"firepower": 1}, "conditions": {}}],
            },
        ]
        (root / "equipment" / "special-bonuses.nedb").write_text(
            "".join(json.dumps(record) + "\n" for record in bonuses), encoding="utf-8"
        )
        Image.new("RGBA", (270, 270), (20, 40, 60, 255)).save(
            root / "assets" / "useitem" / "1.webp",
            "WEBP",
            quality=93,
        )
        Image.new("RGBA", (270, 270), (20, 40, 60, 255)).save(
            compatibility_root / "assets" / "useitem" / "1.png",
            "PNG",
        )

    def test_inspection_detects_consumer_data_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_package(root)
            baseline = inspect_package(root)
            self.assertEqual(baseline["metrics"]["improvement.detailRecordCount"], 3)
            self.assertEqual(baseline["metrics"]["improvement.effectExpectationAvailableCount"], 3)
            self.assertEqual(baseline["metrics"]["improvement.routeCount"], 3)
            self.assertEqual(baseline["metrics"]["improvement.stepCount"], 33)
            self.assertEqual(baseline["metrics"]["equipmentDropFrom.relationCount"], 2)
            self.assertEqual(
                baseline["metrics"]["equipmentSpecialBonuses.equipmentTypeRecordCount"],
                1,
            )

            self._write_package(root, item_count=4)
            current = inspect_package(root)
            self.assertNotEqual(current["contentDigest"], baseline["contentDigest"])

    def test_default_quality_config_does_not_gate_compressed_image_total_bytes(self):
        config_path = Path(__file__).resolve().parents[1] / "configs" / "data_quality.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        ratios = config.get("relativeMinimumRatios", {})
        self.assertNotIn("useitemIcons.totalBytes", ratios)
        self.assertEqual(ratios.get("useitemIcons.count"), 0.8)

    def test_relative_drop_is_rejected(self):
        baseline = {
            "metrics": {"improvement.detailRecordCount": 100},
            "files": {"improvement/detail.nedb": {"bytes": 1000}},
        }
        current = {
            "metrics": {"improvement.detailRecordCount": 50},
            "files": {"improvement/detail.nedb": {"bytes": 500}},
        }
        config = {
            "minimums": {},
            "relativeMinimumRatios": {"improvement.detailRecordCount": 0.8},
            "fileSizeMinimumRatio": 0.7,
            "fileSizePaths": ["improvement/detail.nedb"],
        }
        errors = validate_against_baseline(baseline, current, config)
        self.assertEqual(len(errors), 2)

    def test_unsupported_special_bonus_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_package(root)
            record = {
                "target": {"kind": "equipment", "equipmentIds": [315]},
                "equipmentId": 315,
                "equipmentName": "SG レーダー(初期型)",
                "rules": [{
                    "bonus": {"firepower": 1},
                    "sourceBonusFields": {"futureStat": 1},
                    "conditions": {},
                }],
            }
            (root / "equipment" / "special-bonuses.nedb").write_text(
                json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(QualityGateError, "unsupported bonus fields: futureStat"):
                inspect_package(root)

    def test_stale_external_dataset_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_package(root)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            manifest["datasets"]["equipmentDropFrom"]["status"] = "stale"
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(QualityGateError):
                inspect_package(root, require_fresh_sources=True)

    def test_stale_canonical_improvement_dataset_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_package(root)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            manifest["datasets"]["improvement"]["status"] = "stale"
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(QualityGateError, "improvement is not fresh"):
                inspect_package(root, require_fresh_sources=True)

    def test_cache_fallback_fetch_audit_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_package(root)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            fetch_info = manifest["datasets"]["equipmentSpecialBonuses"]["fetches"][0]
            fetch_info["validatedInRun"] = False
            fetch_info["usedCacheFallback"] = True
            fetch_info["status"] = "stale"
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(QualityGateError, "not fresh|not revalidated"):
                inspect_package(root, require_fresh_sources=True)

    def test_missing_referenced_useitem_icon_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_package(root)
            (root / "assets" / "useitem" / "1.webp").unlink()
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            manifest["datasets"]["useitemIcons"]["availableIds"] = []
            manifest["datasets"]["useitemIcons"]["missingIds"] = [1]
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(QualityGateError, "required canonical use-item WebP assets are missing"):
                inspect_package(root)


if __name__ == "__main__":
    unittest.main()
