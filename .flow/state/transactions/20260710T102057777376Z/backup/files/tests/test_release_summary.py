from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleaseSummaryTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("release_summary", ROOT / "script/project/release_summary.py")
        assert spec and spec.loader
        self.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.module
        spec.loader.exec_module(self.module)
        from script.project.runtime import load
        self.runtime = load()

    def test_summary_builder_is_project_owned(self):
        self.assertEqual(self.runtime["stable"]["summary"]["builder"], "script.project.release_summary:build")

    def test_summary_is_deterministic_and_public_only(self):
        first, first_report = self.module.build()
        second, second_report = self.module.build()
        self.assertEqual(first, second)
        self.assertEqual(first_report["summary"]["outputSha256"], second_report["summary"]["outputSha256"])
        self.assertIn((ROOT / "VERSION").read_text("utf-8").strip(), first)
        forbidden = re.compile(r"(?:\.flow|\.devops|origin/dev|main-origin|GITEA_TOKEN|NPM_TOKEN|Receipt|Evidence)", re.I)
        self.assertIsNone(forbidden.search(first))

    def test_internal_report_aggregates_all_declared_change_sources(self):
        _, report = self.module.build()
        self.assertEqual(
            [item["path"] for item in report["sources"]],
            ["CHANGELOG.md", "packages/kancolle-data/CHANGELOG.md", "packages/kancolle-data/RELEASES.json", "git log"],
        )
        self.assertGreater(report["summary"]["changelogEntryCount"], 0)
        self.assertIsInstance(report["gitCommits"], list)
        self.assertTrue(all("public" in entry for entry in report["changelogEntries"]))

    def test_internal_aggregate_includes_structured_quality_and_data_evidence(self):
        _, report = self.module.build()
        paths = {item["path"] for item in report["structuredEvidence"]}
        self.assertIn(".flow/state/checks/after.json", paths)
        self.assertIn("dist/packages/kancolle-data/audit/build-report.json", paths)
        self.assertIn("dist/data-pipeline/sources/comparison/summary.json", paths)
        self.assertEqual(report["aggregationPolicy"]["public"], "只输出用户与数据消费方面向的 RELEASE-NOTES.md")


if __name__ == "__main__":
    unittest.main()
