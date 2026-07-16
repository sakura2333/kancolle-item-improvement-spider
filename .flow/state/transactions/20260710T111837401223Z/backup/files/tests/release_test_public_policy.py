from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PublicReleasePolicyTest(unittest.TestCase):
    def setUp(self):
        from script.project.runtime import load
        self.runtime = load()
        self.stable = self.runtime["stable"]

    def test_all_public_technical_docs_and_source_evidence_are_included(self):
        include = self.stable["include"]
        self.assertIn("docs/public/**", include)
        self.assertNotIn("dist/data-pipeline/sources/**", include)
        self.assertIn("dist/data-pipeline/sources/**", self.stable["generatedState"])
        for retired in ("CHANGELOG.md", "DATA_PACKAGE_NOTES.md", "DATA_SCHEMA.md", "ROUTE_AUDIT_NOTES.md"):
            self.assertNotIn(retired, include)
            self.assertFalse((ROOT / retired).exists())

    def test_flow_and_maintenance_materials_are_internal_only(self):
        internal = self.stable["internalOnly"]
        for required in (".flow/**", "script/**", "tests/**", "docs/internal/**", "AGENTS.md", "GPT-START.md"):
            self.assertIn(required, internal)
        self.assertNotIn(".flow/**", self.stable["include"])
        self.assertNotIn("script/**", self.stable["include"])

    def test_public_summary_filters_internal_details(self):
        public = (ROOT / "RELEASE-NOTES.md").read_text("utf-8")
        forbidden = re.compile(r"(?:\.flow|\.devops|origin/dev|main-origin|GITEA_TOKEN|NPM_TOKEN|Receipt|Evidence)", re.I)
        self.assertIsNone(forbidden.search(public))

    def test_no_destructive_github_cleanup_implementation(self):
        forbidden = ("public:purge", "/actions/runs", "/actions/artifacts", "/actions/caches", "/actions/secrets", "/actions/variables")
        hits = []
        for path in [ROOT / ".flow/project.json", *sorted((ROOT / "script").rglob("*.py"))]:
            text = path.read_text("utf-8")
            for token in forbidden:
                if token in text:
                    hits.append(f"{path.relative_to(ROOT)}:{token}")
        self.assertEqual(hits, [])

    def test_public_actions_are_split_and_not_flow_control_plane(self):
        self.assertIn(".github/workflows/**", self.stable["include"])
        for name in ("source-acquire.yml", "data-build.yml", "release.yml"):
            workflow = (ROOT / ".github/workflows" / name).read_text("utf-8")
            self.assertNotIn("stable:release", workflow)
            self.assertNotIn("./flow", workflow)
            self.assertNotIn("script/", workflow)

    def test_main_release_review_gate_is_project_owned_and_code_only(self):
        self.assertEqual(self.stable["mainReleaseGateRoot"], ".flow/state/main-release")
        self.assertEqual(self.stable["candidateBranchPrefix"], "public-candidate/")
        self.assertIn(".flow/**", self.stable["internalOnly"])
        stable_source = (ROOT / "script/project/stable_command.py").read_text("utf-8")
        self.assertNotIn('git", "push"', stable_source)
        collaboration = (ROOT / "script/project/main_release.py").read_text("utf-8")
        self.assertIn("public-candidate", collaboration)
        self.assertIn("open_gate", collaboration)

    def test_data_release_action_owns_latest_and_improvement2(self):
        self.assertNotIn("npmRelease", self.stable)
        release_workflow = (ROOT / ".github/workflows/release.yml").read_text("utf-8")
        release_module = (ROOT / "automation/release/npm_release_set.py").read_text("utf-8")
        self.assertIn("automation.release.npm_publish", release_workflow)
        self.assertIn('CURRENT_TAG = "latest"', release_module)
        self.assertIn('IMPROVEMENT2_TAG = "improvement2"', release_module)
        self.assertIn('IMPROVEMENT2_CONSUMER = "poi-plugin-item-improvement2"', release_module)
        stable_source = (ROOT / "script/project/stable_command.py").read_text("utf-8")
        self.assertNotIn("npm publish", stable_source)
        self.assertNotIn("npmRelease", stable_source)

    def test_stable_content_manifest_enforces_one_time_cleanup_then_incremental(self):
        content = self.stable["contentManifest"]
        self.assertEqual(content["mode"], "one-time-full-then-managed")
        self.assertEqual(content["migrationId"], "spider-flow-public-1.0.6")
        self.assertEqual(content["allowedLegacyTrees"], ["4065dfa2cc3732c2c2ca70d60ec889dc24d738fe"])
        self.assertIn("STABLE-CONTENT-MANIFEST.json", self.stable["generated"])


    def test_legacy_exact_release_receipts_are_removed_from_public_data(self):
        for rel in (
            "data/release/exact-stable-baseline.json",
            "data/release/stable-baseline.json",
        ):
            self.assertFalse((ROOT / rel).exists(), rel)
            self.assertNotIn(rel, self.stable["include"])

    def test_internal_architecture_nodes_never_enter_public_main(self):
        self.assertIn("docs/internal/**", self.stable["internalOnly"])
        self.assertNotIn("docs/internal/**", self.stable["include"])


if __name__ == "__main__":
    unittest.main()
