from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from service.data_package.equipment_acquisition_snapshot import (
    AcquisitionSnapshotError,
    refresh_or_reuse_acquisition_snapshot,
    validate_acquisition_snapshot,
)


def _write_lines(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values),
        encoding="utf-8",
    )


def _write_valid_snapshot(root: Path) -> None:
    records = [{
        "equipmentId": 3,
        "equipmentName": "10cm連装高角砲",
        "source": "wikiwiki-equipment-detail",
        "schemaVersion": 3,
        "accepted": True,
        "resolvedShipIds": [],
        "resolvedQuestKeys": [],
    }]
    catalog = [{
        "equipmentId": 3,
        "equipmentName": "10cm連装高角砲",
        "sourceUrl": "https://wikiwiki.jp/kancolle/test",
        "cacheKey": "wikiwiki.jp/kancolle/test.html",
    }]
    issues = [{"kind": "raw-page-missing"}]
    references: list[dict] = []
    unclassified: list[dict] = []
    root.mkdir(parents=True, exist_ok=True)
    (root / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    _write_lines(root / "acquisition-records.nedb", records)
    _write_lines(root / "dataset-issues.nedb", issues)
    _write_lines(root / "reference-issues.nedb", references)
    _write_lines(root / "unclassified-evidence.nedb", unclassified)
    (root / "dataset-metadata.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "source": "wikiwiki-equipment-detail",
            "mode": "offline-raw-cache-parse",
            "generatedAt": "2026-07-06T00:00:00+00:00",
            "catalogEntryCount": len(catalog),
            "recordCount": len(records),
            "acceptedRecordCount": len(records),
            "issueCount": len(issues),
            "referenceIssueCount": len(references),
            "unclassifiedEvidenceCount": len(unclassified),
        }),
        encoding="utf-8",
    )


class EquipmentAcquisitionSnapshotTest(unittest.TestCase):
    def test_clean_public_checkout_reuses_validated_snapshot_without_raw_cache(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            output = root / "data" / "sources" / "wikiwiki-equipment-detail"
            raw_root = root / "data" / "raw_data" / "site_cache"
            _write_valid_snapshot(output)

            with mock.patch(
                "service.data_package.equipment_acquisition_snapshot.run_offline_parse"
            ) as parser:
                snapshot = refresh_or_reuse_acquisition_snapshot(
                    raw_root=raw_root,
                    output_dir=output,
                    quest_catalog_text="{}",
                    allow_incomplete=False,
                )

            parser.assert_not_called()
            self.assertEqual(snapshot.input_mode, "validated-public-snapshot")
            self.assertEqual([record["equipmentId"] for record in snapshot.records], [3])

    def test_ordinary_http_cache_metadata_does_not_replace_public_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            output = root / "output"
            raw_root = root / "raw"
            raw_root.mkdir(parents=True)
            _write_valid_snapshot(output)
            (raw_root / "_meta.json").write_text(
                json.dumps({
                    "wikiwiki.jp/kancolle/改修表.html": {
                        "url": "https://wikiwiki.jp/kancolle/改修表",
                        "fetch_status": "fresh",
                    }
                }),
                encoding="utf-8",
            )

            with mock.patch(
                "service.data_package.equipment_acquisition_snapshot.run_offline_parse"
            ) as parser:
                snapshot = refresh_or_reuse_acquisition_snapshot(
                    raw_root=raw_root,
                    output_dir=output,
                    quest_catalog_text="{}",
                    allow_incomplete=False,
                )

            parser.assert_not_called()
            self.assertEqual(snapshot.input_mode, "validated-public-snapshot")
            self.assertEqual([record["equipmentId"] for record in snapshot.records], [3])

    def test_local_acquisition_raw_cache_is_rebuilt_before_snapshot_is_consumed(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            output = root / "output"
            raw_root = root / "raw"
            raw_root.mkdir(parents=True)
            (raw_root / "_meta.json").write_text(
                json.dumps({
                    "wikiwiki.jp/kancolle/test.html": {
                        "url": "https://wikiwiki.jp/kancolle/test",
                        "acquisition_source": "external-browser-session-crawl",
                        "equipmentId": 3,
                    }
                }),
                encoding="utf-8",
            )

            def fake_parse(**kwargs):
                self.assertEqual(kwargs["raw_root"], raw_root.resolve())
                _write_valid_snapshot(output)

            with mock.patch(
                "service.data_package.equipment_acquisition_snapshot.run_offline_parse",
                side_effect=fake_parse,
            ) as parser:
                snapshot = refresh_or_reuse_acquisition_snapshot(
                    raw_root=raw_root,
                    output_dir=output,
                    quest_catalog_text="{}",
                    allow_incomplete=False,
                )

            parser.assert_called_once()
            self.assertEqual(snapshot.input_mode, "local-raw-cache")

    def test_missing_raw_cache_and_missing_snapshot_fails_by_default(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            with self.assertRaisesRegex(
                AcquisitionSnapshotError,
                "public snapshot is incomplete",
            ):
                refresh_or_reuse_acquisition_snapshot(
                    raw_root=root / "raw",
                    output_dir=root / "output",
                    quest_catalog_text="{}",
                    allow_incomplete=False,
                )

    def test_missing_snapshot_can_be_ordered_as_source_unavailable_placeholder(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            output = root / "output"
            snapshot = refresh_or_reuse_acquisition_snapshot(
                raw_root=root / "raw",
                output_dir=output,
                quest_catalog_text="{}",
                allow_incomplete=False,
                allow_missing_snapshot=True,
            )

            self.assertEqual(snapshot.input_mode, "missing-source-snapshot")
            self.assertEqual(snapshot.records, [])
            self.assertTrue((output / "acquisition-records.nedb").is_file())
            metadata = json.loads((output / "dataset-metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "source-unavailable")
            self.assertEqual(metadata["recordCount"], 0)
            issues = (output / "dataset-issues.nedb").read_text(encoding="utf-8")
            self.assertIn("source-snapshot-missing", issues)


    def test_corrupt_snapshot_is_not_hidden_by_missing_snapshot_fallback(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            output = root / "output"
            _write_valid_snapshot(output)
            (output / "acquisition-records.nedb").write_text("{invalid\n", encoding="utf-8")

            with self.assertRaisesRegex(AcquisitionSnapshotError, "NDJSON is invalid"):
                refresh_or_reuse_acquisition_snapshot(
                    raw_root=root / "raw",
                    output_dir=output,
                    quest_catalog_text="{}",
                    allow_incomplete=False,
                    allow_missing_snapshot=True,
                )

    def test_invalid_snapshot_ndjson_fails(self):
        with tempfile.TemporaryDirectory() as temp_name:
            output = Path(temp_name) / "output"
            _write_valid_snapshot(output)
            (output / "acquisition-records.nedb").write_text("{invalid\n", encoding="utf-8")

            with self.assertRaisesRegex(AcquisitionSnapshotError, "NDJSON is invalid"):
                validate_acquisition_snapshot(output)

    def test_zero_record_snapshot_fails(self):
        with tempfile.TemporaryDirectory() as temp_name:
            output = Path(temp_name) / "output"
            _write_valid_snapshot(output)
            (output / "acquisition-records.nedb").write_text("", encoding="utf-8")
            metadata_path = output / "dataset-metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["recordCount"] = 0
            metadata["acceptedRecordCount"] = 0
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            with self.assertRaisesRegex(
                AcquisitionSnapshotError,
                "contains no accepted records",
            ):
                validate_acquisition_snapshot(output)

    def test_snapshot_count_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as temp_name:
            output = Path(temp_name) / "output"
            _write_valid_snapshot(output)
            metadata_path = output / "dataset-metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["recordCount"] = 2
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            with self.assertRaisesRegex(AcquisitionSnapshotError, "count mismatch"):
                validate_acquisition_snapshot(output)


if __name__ == "__main__":
    unittest.main()
