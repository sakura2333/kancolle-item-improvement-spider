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
        for required in (".flow/**", "script/**", "tests/**", "docs/internal/**", "AGENTS.md"):
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
        self.assertEqual(self.stable["previewRoot"], ".flow/state/public-candidates")
        self.assertEqual(self.stable["mainReleaseGateRoot"], ".flow/state/main-release")
        self.assertEqual(self.stable["candidateBranchPrefix"], "public-candidate/")
        self.assertEqual(self.stable["betaCandidateBranchPrefix"], "public-beta/")
        self.assertIn(".flow/**", self.stable["internalOnly"])
        stable_source = (ROOT / "script/project/stable_command.py").read_text("utf-8")
        self.assertNotIn('git", "push"', stable_source)
        collaboration = (ROOT / "script/project/main_release.py").read_text("utf-8")
        self.assertIn("public-candidate", collaboration)
        self.assertIn("public-beta", collaboration)
        self.assertIn("prepare-beta", collaboration)
        self.assertIn("shared-whitelist-public-snapshot", collaboration)
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

    def test_public_snapshot_manifest_separates_public_set_from_internal_migration(self):
        content = self.stable["contentManifest"]
        self.assertEqual(content["path"], "PUBLIC-CONTENT-MANIFEST.json")
        self.assertEqual(content["mode"], "one-time-full-then-managed")
        self.assertEqual(content["legacyPaths"], ["STABLE-CONTENT-MANIFEST.json"])
        self.assertNotIn("migrationId", content)
        self.assertIn("PUBLIC-CONTENT-MANIFEST.json", self.stable["generated"])

    def test_root_ai_index_is_single_and_internal(self):
        self.assertTrue((ROOT / "AGENTS.md").is_file())
        for retired in ("GPT-START.md", "SPIDER-HARD-RULES.md", "SPIDER-AUTHORITY-MAP.md"):
            self.assertFalse((ROOT / retired).exists(), retired)
        for internal in (
            "docs/internal/ai/START.md",
            "docs/internal/ai/HARD-RULES.md",
            "docs/internal/ai/AUTHORITY-MAP.md",
        ):
            self.assertTrue((ROOT / internal).is_file(), internal)
            self.assertNotIn(internal, self.stable["include"])

    def test_beta_and_stable_share_whitelist_snapshot_policy(self):
        self.assertEqual(self.stable["policy"], "whitelist-public-snapshot")
        self.assertEqual(self.stable["channels"], ["beta", "stable"])
        self.assertNotIn("betaExcluded", self.stable)


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

    def test_public_runtime_state_is_not_flow_state(self):
        public_roots = [
            ROOT / "README.md",
            ROOT / "configs",
            ROOT / "automation",
            ROOT / "service",
            ROOT / "util",
            ROOT / "docs/public",
        ]
        offenders = []
        for base in public_roots:
            paths = [base] if base.is_file() else list(base.rglob("*"))
            for path in paths:
                if not path.is_file() or path.suffix == ".pyc":
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                if ".flow/" in text:
                    offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])
        self.assertIn(".spider/local/", (ROOT / ".gitignore").read_text("utf-8"))

    def test_public_exceptions_are_explicit_and_bound(self):
        declaration = json.loads((ROOT / "release/public-content.json").read_text(encoding="utf-8"))
        exceptions = json.loads((ROOT / declaration["exceptionsFile"]).read_text(encoding="utf-8"))
        self.assertEqual(declaration["schemaVersion"], 3)
        self.assertEqual(exceptions["policy"], "deny-by-default-explicit-public-exceptions")
        self.assertEqual(
            [entry["id"] for entry in exceptions["exceptions"]],
            ["github-secret-name-npm-token", "source-validation-ai-review-feature"],
        )
        for entry in exceptions["exceptions"]:
            self.assertTrue(entry["reason"])
            self.assertTrue(entry["owner"])
            self.assertEqual(entry["review"], "mechanical-and-ai")

    def test_public_gitignore_is_generated_and_required(self):
        self.assertIn(".gitignore", self.stable["generated"])
        self.assertIn(".gitignore", self.stable["required"])
        self.assertIn(".spider/local/", self.stable["publicGitignore"])


if __name__ == "__main__":
    unittest.main()
