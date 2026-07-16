import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from service.data_package import builder, manifest_builder
from service.operator_stop import OperatorStopError
from service.data_package import projection, source_collection
from service.data_package.equipment_bonus import parse_special_bonuses
from service.data_package.equipment_drop_from import DropFromIssue, parse_drop_from
from util.start2.start2_item_utils import start2ItemUtils
from util.start2.start2_ship_utils import ship_utils


class DataPackageBuilderContractTest(unittest.TestCase):
    def test_builder_uses_the_manifest_package_version_reader(self):
        self.assertIs(builder.package_version, manifest_builder.package_version)
        package = json.loads((builder.PACKAGE_DIR / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(builder.package_version(), package["version"])


class DataPackageParserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.item_utils = start2ItemUtils.load()
        cls.ship_utils = ship_utils.load()

    def test_drop_from_initial_and_remodel(self):
        ships = {
            "Fubuki": {
                "_api_id": 9,
                "_japanese_name": "吹雪",
                "_remodel_from": False,
                "_equipment": [
                    {"equipment": "Type A", "size": 0},
                    {"equipment": "Type A", "size": 0},
                ],
            },
            "Fubuki Kai Ni": {
                "_api_id": 426,
                "_japanese_name": "吹雪改二",
                "_remodel_from": "Fubuki/Kai",
                "_remodel_level": 70,
                "_equipment": [{"equipment": "Type B", "size": 0}],
            },
        }
        equipment = {
            "Type A": {"_id": 1, "_japanese_name": "12cm単装砲"},
            "Type B": {"_id": 106, "_japanese_name": "13号対空電探改"},
        }
        records, issues, metadata = parse_drop_from(
            ships, equipment, self.item_utils, self.ship_utils
        )
        self.assertFalse(issues)
        by_id = {record["equipmentId"]: record for record in records}
        self.assertEqual(by_id[1]["sources"][0]["quantity"], 2)
        self.assertEqual(by_id[1]["sources"][0]["method"], "initial")
        self.assertEqual(by_id[106]["sources"][0]["method"], "remodel")
        self.assertEqual(by_id[106]["sources"][0]["remodelLevel"], 70)
        self.assertEqual(metadata["relationCount"], 3)


    def test_drop_from_resolves_human_accepted_kcwiki_equipment_aliases(self):
        ships = {
            "Musashi Kai Ni": {
                "_api_id": 546,
                "_japanese_name": "武蔵改二",
                "_equipment": [
                    {"equipment": "15m Duplex Rangefinder + Type 21 Radar Kai Ni", "size": 0},
                    {"equipment": "Ju 87C Kai Ni (w/ KMX)", "size": 0},
                ],
            }
        }
        equipment = {
            "15m Duplex Rangefinder + Type 21 Radar Kai 2": {
                "_id": 142,
                "_japanese_name": "15m二重測距儀+21号電探改二",
            },
            "Ju 87C Kai 2 (w/ KMX)": {
                "_id": 305,
                "_japanese_name": "Ju87C改二(KMX搭載機)",
            },
        }
        records, issues, metadata = parse_drop_from(
            ships, equipment, self.item_utils, self.ship_utils
        )
        self.assertFalse(issues)
        self.assertEqual({142, 305}, {record["equipmentId"] for record in records})
        self.assertEqual(2, metadata["semanticAliasMatchCount"])

    def test_strict_optional_dataset_collection_rejects_unresolved_mappings(self):
        record = {"equipmentId": 1, "equipmentName": "x", "sources": []}
        issue = DropFromIssue(kind="unresolved-equipment", message="unresolved")
        metadata = {"relationCount": 1, "issueCount": 1, "schemaVersion": 1}
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            source_collection, "SOURCE_ROOT", Path(temp_dir)
        ), patch.object(
            source_collection, "_load_json", side_effect=[({}, {}), ({}, {})]
        ), patch.object(
            source_collection, "parse_drop_from", return_value=([record], [issue], metadata)
        ):
            with self.assertRaisesRegex(OperatorStopError, "无法自动确认"):
                source_collection.collect_optional_datasets(strict=True)


    def test_strict_kcwiki_raw_fetch_failure_is_non_blocking(self):
        bonus_record = {
            "target": {"kind": "equipment", "equipmentIds": [1]},
            "equipmentId": 1,
            "equipmentName": "12cm単装砲",
            "rules": [{"bonus": {"firepower": 1}, "conditions": {}}],
        }
        fetch_meta = {
            "contentSha256": "source-sha",
            "status": "fresh",
            "validatedInRun": True,
            "usedCacheFallback": False,
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            source_collection, "SOURCE_ROOT", Path(temp_dir)
        ), patch.object(
            source_collection,
            "_load_json",
            side_effect=[
                RuntimeError("kcwiki offline"),
                ({"101": {"code": "A1", "name": "Test Quest"}}, fetch_meta),
                ({}, fetch_meta),
            ],
        ), patch.object(
            source_collection,
            "parse_special_bonuses",
            return_value=([bonus_record], [], {"ruleCount": 1, "schemaVersion": 2}),
        ), patch.object(source_collection.simple_logger, "error") as log_error:
            result = source_collection.collect_optional_datasets(strict=True)

        self.assertEqual(result["dropFrom"]["metadata"]["status"], "failed")
        self.assertIn("kcwiki offline", result["dropFrom"]["metadata"]["error"])
        self.assertTrue(any(
            "KCWIKI RAW UNAVAILABLE" in str(call.args[0])
            for call in log_error.call_args_list
        ))

    def test_asset_cleanup_removes_legacy_directory_aliases(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            projection, "PACKAGE_DIR", Path(temp_dir)
        ):
            root = Path(temp_dir)
            for relative in (
                "assets/useitems",
                "assets/equipment",
                "assets/useitem",
                "assets/equip",
            ):
                path = root / relative
                path.mkdir(parents=True, exist_ok=True)
                (path / "1.png").write_bytes(b"legacy")

            projection._clear_regenerated()

            self.assertFalse((root / "assets/useitems").exists())
            self.assertFalse((root / "assets/equipment").exists())
            self.assertTrue((root / "assets/useitem").is_dir())
            self.assertTrue((root / "assets/equip").is_dir())
            self.assertFalse((root / "assets/useitem/1.png").exists())
            self.assertFalse((root / "assets/equip/1.webp").exists())

    def test_kcwiki_projection_reuses_unchanged_input_hashes(self):
        record = {
            "equipmentId": 1,
            "equipmentName": "12cm単装砲",
            "sources": [{
                "shipId": 9, "shipName": "吹雪", "method": "initial",
                "quantity": 1, "slotIndices": [0], "slotSizes": [0],
                "sourceShipRef": "Fubuki",
            }],
        }
        drop_metadata = {
            "source": "kcwiki-data",
            "relationCount": 1,
            "issueCount": 0,
            "schemaVersion": 1,
            "inputHashes": {"ship": "ship-sha", "equipment": "equipment-sha"},
        }
        bonus_record = {
            "target": {"kind": "equipment", "equipmentIds": [1]},
            "equipmentId": 1,
            "equipmentName": "12cm単装砲",
            "rules": [{"bonus": {"firepower": 1}, "conditions": {}}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "kcwiki-data"
            source_dir.mkdir(parents=True)
            (source_dir / "equipment-drop-from.nedb").write_text(
                json.dumps(record) + "\n", encoding="utf-8"
            )
            (source_dir / "dataset-issues.nedb").write_text("\n", encoding="utf-8")
            (source_dir / "dataset-metadata.json").write_text(
                json.dumps(drop_metadata), encoding="utf-8"
            )
            loads = [
                ({}, {"contentSha256": "ship-sha", "status": "fresh", "validatedInRun": True, "usedCacheFallback": False}),
                ({}, {"contentSha256": "equipment-sha", "status": "fresh", "validatedInRun": True, "usedCacheFallback": False}),
                ({"101": {"code": "A1", "name": "Test Quest"}}, {"contentSha256": "quest-sha", "status": "fresh", "validatedInRun": True, "usedCacheFallback": False}),
                ({}, {"contentSha256": "bonus-sha", "status": "fresh", "validatedInRun": True, "usedCacheFallback": False}),
            ]
            with patch.object(source_collection, "SOURCE_ROOT", root), patch.object(
                source_collection, "_load_json", side_effect=loads
            ), patch.object(source_collection, "parse_drop_from") as parse_drop, patch.object(
                source_collection, "parse_special_bonuses",
                return_value=([bonus_record], [], {"ruleCount": 1, "schemaVersion": 2}),
            ):
                result = source_collection.collect_optional_datasets(strict=False)
            parse_drop.assert_not_called()
            self.assertEqual(
                result["dropFrom"]["metadata"]["incremental"]["mode"],
                "reuse-unchanged-inputs",
            )
            self.assertEqual(result["questCatalog"]["metadata"]["questCount"], 1)
            self.assertEqual(len(result["specialBonuses"]["records"]), 1)

    def test_special_bonus_preserves_complex_conditions(self):
        catalog = [
            {
                "ids": [1],
                "bonuses": [
                    {
                        "bonus": {"houg": 2, "kaih": 1},
                        "shipId": [9, 201],
                        "level": 7,
                        "num": 1,
                        "requiresSR": 1,
                        "shipCountry": ["JP", "DE"],
                        "customFlag": "keep-me",
                    }
                ],
            }
        ]
        records, issues, metadata = parse_special_bonuses(
            catalog, self.item_utils, self.ship_utils
        )
        self.assertFalse(issues)
        rule = records[0]["rules"][0]
        self.assertEqual(rule["bonus"], {"firepower": 2, "evasion": 1})
        self.assertEqual(rule["conditions"]["shipIds"], [9, 201])
        self.assertEqual(rule["conditions"]["minImprovement"], 7)
        self.assertEqual(rule["conditions"]["equipmentCount"], 1)
        self.assertEqual(rule["conditions"]["requires"]["surfaceRadar"], 1)
        self.assertEqual(rule["conditions"]["shipCountries"], ["JP", "DE"])
        self.assertEqual(rule["conditions"]["sourceFields"]["customFlag"], "keep-me")
        self.assertEqual(metadata["ruleCount"], 1)

    def test_special_bonus_normalizes_range_bonus(self):
        catalog = [
            {
                "ids": [315],
                "bonuses": [
                    {
                        "bonus": {"leng": 1},
                        "shipId": [519],
                    }
                ],
            }
        ]
        records, issues, metadata = parse_special_bonuses(
            catalog, self.item_utils, self.ship_utils
        )
        self.assertFalse(issues)
        self.assertEqual(records[0]["equipmentId"], 315)
        self.assertEqual(records[0]["rules"][0]["bonus"], {"range": 1})
        self.assertNotIn("sourceBonusFields", records[0]["rules"][0])
        self.assertEqual(metadata["ruleCount"], 1)


    def test_source_status_requires_current_run_validation(self):
        self.assertEqual(
            source_collection._source_status([{
                "status": "fresh",
                "validatedInRun": True,
                "usedCacheFallback": False,
            }]),
            "ok",
        )
        self.assertEqual(
            source_collection._source_status([{
                "status": "fresh",
                "validatedInRun": False,
                "usedCacheFallback": False,
            }]),
            "stale",
        )

    def test_strict_improvement_source_requires_current_run_validation(self):
        source_metadata = {
            "status": "ok",
            "scheduleCount": 10,
            "issueCount": 0,
            "generatedAt": "2026-06-29T00:00:00+00:00",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            metadata_path = Path(temp_dir) / "metadata.json"
            metadata_path.write_text(json.dumps(source_metadata), encoding="utf-8")
            fresh_fetch = {
                "url": source_collection.AKASHI_URL,
                "status": "fresh",
                "validatedInRun": True,
                "usedCacheFallback": False,
            }
            with patch.object(source_collection, "AKASHI_METADATA_PATH", metadata_path), patch.object(
                source_collection, "_fetch_summary", return_value=fresh_fetch
            ), patch.object(source_collection, "collection_completed_in_run", return_value=True):
                metadata = source_collection._improvement_source_metadata(strict=True)
            self.assertEqual(metadata["status"], "ok")
            self.assertTrue(metadata["collectionCompletedInRun"])

            stale_fetch = {**fresh_fetch, "validatedInRun": False}
            with patch.object(source_collection, "AKASHI_METADATA_PATH", metadata_path), patch.object(
                source_collection, "_fetch_summary", return_value=stale_fetch
            ), patch.object(source_collection, "collection_completed_in_run", return_value=False):
                with self.assertRaisesRegex(ValueError, "not freshly validated"):
                    source_collection._improvement_source_metadata(strict=True)

    def test_cached_icons_are_promoted_to_stable_assets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_dir = root / "cache"
            webp_dir = root / "webp"
            static_dir = root / "static"
            cache_dir.mkdir()
            webp_dir.mkdir()
            image = cache_dir / "71.png"
            webp = webp_dir / "71.webp"
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 128)
            webp.write_bytes(b"RIFF" + (128).to_bytes(4, "little") + b"WEBP" + b"x" * 128)
            with patch.object(projection, "CACHE_IMAGE_DIR", cache_dir), patch.object(
                projection, "CACHE_USEITEM_WEBP_DIR", webp_dir
            ), patch.object(
                projection, "STATIC_IMAGE_DIR", static_dir
            ):
                projection._promote_cached_icons()
            self.assertEqual((static_dir / "71.png").read_bytes(), image.read_bytes())
            self.assertEqual((static_dir / "71.webp").read_bytes(), webp.read_bytes())

    def test_cached_equipment_images_are_promoted_to_stable_assets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_dir = root / "cache"
            static_dir = root / "static"
            cache_dir.mkdir()
            static_dir.mkdir()
            (static_dir / "61.png").write_bytes(b"legacy")
            image = cache_dir / "61.webp"
            image.write_bytes(b"RIFF" + (128).to_bytes(4, "little") + b"WEBP" + b"equipment" * 16)
            with patch.object(projection, "CACHE_EQUIPMENT_IMAGE_DIR", cache_dir), patch.object(
                projection, "STATIC_EQUIPMENT_IMAGE_DIR", static_dir
            ):
                projection._promote_cached_equipment_images()
            self.assertEqual((static_dir / "61.webp").read_bytes(), image.read_bytes())
            self.assertFalse((static_dir / "61.png").exists())

    def test_special_bonus_preserves_equipment_type_targets(self):
        catalog = [
            {
                "types": [9, 10],
                "bonuses": [
                    {
                        "bonus": {"houg": 1},
                        "shipType": [2],
                    }
                ],
            }
        ]
        records, issues, metadata = parse_special_bonuses(
            catalog, self.item_utils, self.ship_utils
        )
        self.assertFalse(issues)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["target"]["kind"], "equipment-type")
        self.assertEqual(records[0]["equipmentTypeIds"], [9, 10])
        self.assertEqual(records[0]["rules"][0]["bonus"], {"firepower": 1})
        self.assertEqual(metadata["equipmentTypeRecordCount"], 1)
        self.assertEqual(metadata["schemaVersion"], 2)



class DataPackageManifestBuilderTest(unittest.TestCase):
    def test_refresh_manifest_excludes_internal_compatibility_staging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir)
            compatibility_manifest = (
                package_dir
                / "compat"
                / "poi-plugin-item-improvement2"
                / "manifest.json"
            )
            compatibility_manifest.parent.mkdir(parents=True)
            schemas = package_dir / "schemas"
            schemas.mkdir()
            (package_dir / "package.json").write_text(
                json.dumps({"version": "0.5.1"}), encoding="utf-8"
            )
            (package_dir / "manifest.json").write_text(
                json.dumps({"packageVersion": "0.5.0", "files": {}}),
                encoding="utf-8",
            )
            compatibility_manifest.write_text(
                json.dumps({"consumer": "poi-plugin-item-improvement2"}),
                encoding="utf-8",
            )
            (schemas / "improvement-detail-v3.schema.json").write_text("{}", encoding="utf-8")
            (schemas / "improvement-detail.schema.json").write_text("{}", encoding="utf-8")

            with patch.object(manifest_builder, "PACKAGE_DIR", package_dir):
                manifest = manifest_builder.refresh_package_manifest()

            self.assertEqual(manifest["packageVersion"], "0.5.1")
            self.assertNotIn(
                "compat/poi-plugin-item-improvement2/manifest.json",
                manifest["files"],
            )
            self.assertNotIn("schemas/improvement-detail-v3.schema.json", manifest["files"])
            self.assertIn("schemas/improvement-detail.schema.json", manifest["files"])
            self.assertNotIn("manifest.json", manifest["files"])

if __name__ == "__main__":
    unittest.main()
