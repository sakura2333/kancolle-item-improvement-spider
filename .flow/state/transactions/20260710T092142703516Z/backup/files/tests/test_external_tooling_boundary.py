from __future__ import annotations

import json
import unittest
from pathlib import Path

from script.project.ownership import classify_path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "wikiwiki-crawler"


class ExternalToolingBoundaryTest(unittest.TestCase):
    def test_guard_and_manifest_define_external_boundary(self):
        guard = (TOOL / "ARCHITECTURE-GUARD.md").read_text("utf-8")
        self.assertIn("manual browser-session acquisition source", guard)
        self.assertIn("subprocess wrapper", guard)
        manifest = json.loads((TOOL / "FLOW-EXCLUSION.manifest.json").read_text("utf-8"))
        self.assertEqual(manifest["classification"], "manual-browser-session-source")
        self.assertTrue(manifest["flow"]["registered"])
        self.assertEqual(manifest["flow"]["command"], "wikiwiki")
        self.assertEqual(manifest["flow"]["execution"], "manual-only")
        self.assertTrue(manifest["update"]["artifactDistribution"])
        self.assertFalse(manifest["update"]["executionDuringTransaction"])
        self.assertEqual(manifest["dependencies"]["coreToTool"], "subprocess-wrapper-only")

    def test_core_python_has_no_tool_dependency(self):
        roots = ("script", "service", "pojo", "configs")
        allowed = {"script/project/wikiwiki_command.py"}
        forbidden = ("tools.wikiwiki", "tools/wikiwiki-crawler", "wikiwiki-crawler/crawler.py")
        offenders = []
        for relative_root in roots:
            for path in (ROOT / relative_root).rglob("*.py"):
                relative = path.relative_to(ROOT).as_posix()
                if relative in allowed:
                    continue
                text = path.read_text("utf-8")
                if any(marker in text for marker in forbidden):
                    offenders.append(relative)
        self.assertEqual(offenders, [])

    def test_local_tool_state_is_preserved_and_ignored(self):
        self.assertEqual(
            classify_path(ROOT, "configs/wikiwiki-crawler.local.json"),
            "local-preserved",
        )
        self.assertEqual(
            classify_path(ROOT, ".flow/local/wikiwiki-crawler/raw/3.html"),
            "local-preserved",
        )
        self.assertEqual(
            classify_path(ROOT, ".flow/local/source-cache/wikiwiki.jp/kancolle/test.html"),
            "local-preserved",
        )
        gitignore = (ROOT / ".gitignore").read_text("utf-8")
        self.assertIn(".flow/local/", gitignore)

    def test_tool_is_registered_only_as_thin_flow_command(self):
        adapter = (ROOT / "script/flow_adapter.py").read_text("utf-8")
        self.assertIn('"wikiwiki"', adapter)
        self.assertNotIn("wikiwiki-crawler", adapter)
        self.assertNotIn("tools/", adapter)


if __name__ == "__main__":
    unittest.main()
