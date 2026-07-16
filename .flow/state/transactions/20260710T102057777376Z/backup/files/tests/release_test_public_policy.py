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
        for required in (
            "DATA_PACKAGE_NOTES.md",
            "DATA_SCHEMA.md",
            "ROUTE_AUDIT_NOTES.md",
            "docs/public/**",
            "dist/data-pipeline/sources/**",
        ):
            self.assertIn(required, include)

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

    def test_public_action_is_product_pipeline_not_flow_control_plane(self):
        self.assertIn(".github/workflows/data-pipeline.yml", self.stable["include"])
        workflow = (ROOT / ".github/workflows/data-pipeline.yml").read_text("utf-8")
        self.assertNotIn("stable:release", workflow)
        self.assertNotIn(".flow", workflow)

    def test_main_release_review_gate_is_project_owned_and_generated_state(self):
        self.assertEqual(self.stable["mainReleaseGateRoot"], ".flow/state/main-release")
        self.assertEqual(self.stable["candidateBranchPrefix"], "public-candidate/")
        self.assertIn(".flow/**", self.stable["internalOnly"])
        stable_source = (ROOT / "script/project/stable_command.py").read_text("utf-8")
        self.assertNotIn('git", "push"', stable_source)
        collaboration = (ROOT / "script/project/main_release.py").read_text("utf-8")
        self.assertIn("public-candidate", collaboration)
        self.assertIn("open_gate", collaboration)

    def test_project_stable_release_owns_the_improvement2_npm_projection(self):
        npm_release = self.stable["npmRelease"]
        self.assertEqual(npm_release["package"], "@sakura2333/kancolle-data")
        self.assertEqual(npm_release["currentTag"], "latest")
        self.assertEqual(npm_release["compatibilityConsumer"], "poi-plugin-item-improvement2")
        self.assertEqual(npm_release["compatibilityTag"], "improvement2")
        self.assertEqual(npm_release["publishMode"], "manual-npm-auth-then-flow-reconcile")

    def test_stable_content_manifest_enforces_one_time_cleanup_then_incremental(self):
        content = self.stable["contentManifest"]
        self.assertEqual(content["mode"], "one-time-full-then-managed")
        self.assertEqual(content["migrationId"], "spider-flow-public-1.0.4")
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
