from __future__ import annotations

import unittest
from pathlib import Path

from script.project.ownership import classify_path

ROOT = Path(__file__).resolve().parents[1]


class ExternalToolingBoundaryTest(unittest.TestCase):
    def test_wikiwiki_crawler_is_public_acquisition_automation(self):
        for name in ("crawler.py", "page_catalog.py", "raw_cache.py"):
            self.assertTrue((ROOT / "automation/acquire/wikiwiki" / name).is_file())
            self.assertFalse((ROOT / "tools/wikiwiki-crawler" / name).exists())

    def test_public_automation_has_no_dev_tool_dependency(self):
        offenders = []
        for path in (ROOT / "automation").rglob("*.py"):
            text = path.read_text("utf-8")
            if "script.project" in text or "tools/wikiwiki-crawler" in text:
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])

    def test_local_acquisition_state_is_preserved_and_ignored(self):
        self.assertEqual(classify_path(ROOT, "configs/wikiwiki-crawler.local.json"), "local-preserved")
        self.assertEqual(classify_path(ROOT, ".flow/local/wikiwiki-crawler/raw/3.html"), "local-preserved")
        self.assertEqual(classify_path(ROOT, ".flow/local/source-cache/wikiwiki.jp/kancolle/test.html"), "local-preserved")
        self.assertIn(".flow/local/", (ROOT / ".gitignore").read_text("utf-8"))

    def test_dev_flow_command_is_only_a_local_wrapper(self):
        command = (ROOT / "script/project/wikiwiki_command.py").read_text("utf-8")
        self.assertIn('TOOL_DIR = Path("automation") / "acquire" / "wikiwiki"', command)
        adapter = (ROOT / "script/flow_adapter.py").read_text("utf-8")
        self.assertIn('"wikiwiki"', adapter)


if __name__ == "__main__":
    unittest.main()
