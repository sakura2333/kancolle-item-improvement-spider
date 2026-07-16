from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from script.project.local_runtime_migration import LocalRuntimeMigrationError, migrate_legacy_runtime


class LocalRuntimeMigrationTest(unittest.TestCase):
    def test_moves_complete_legacy_tree_without_touching_flow_config(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            (root / ".flow/local/source-cache/site").mkdir(parents=True)
            (root / ".flow/local/source-cache/site/page.html").write_text("page\n", encoding="utf-8")
            (root / ".flow/local/wikiwiki-crawler/source-receipt.json").parent.mkdir(parents=True)
            (root / ".flow/local/wikiwiki-crawler/source-receipt.json").write_text("{}\n", encoding="utf-8")
            (root / ".flow/local.json").write_text('{"downloadRoot":"/tmp"}\n', encoding="utf-8")

            result = migrate_legacy_runtime(root)

            self.assertEqual(result["status"], "completed")
            self.assertFalse((root / ".flow/local").exists())
            self.assertTrue((root / ".flow/local.json").is_file())
            self.assertEqual((root / ".spider/local/source-cache/site/page.html").read_text(), "page\n")
            receipt = json.loads((root / ".spider/local/migrations/flow-local-to-spider-v1.json").read_text())
            self.assertEqual(receipt["migratedFileCount"], 2)
            self.assertNotIn(str(root), json.dumps(receipt))

    def test_conflict_stops_without_deleting_legacy_state(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            legacy = root / ".flow/local/source-cache/page.html"
            public = root / ".spider/local/source-cache/page.html"
            legacy.parent.mkdir(parents=True)
            public.parent.mkdir(parents=True)
            legacy.write_text("old\n", encoding="utf-8")
            public.write_text("new\n", encoding="utf-8")

            with self.assertRaises(LocalRuntimeMigrationError):
                migrate_legacy_runtime(root)

            self.assertTrue(legacy.is_file())
            self.assertEqual(public.read_text(), "new\n")


if __name__ == "__main__":
    unittest.main()
