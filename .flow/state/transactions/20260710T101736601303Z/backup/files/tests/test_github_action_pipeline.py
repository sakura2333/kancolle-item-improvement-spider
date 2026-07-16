from __future__ import annotations

import re
import unittest
from pathlib import Path


class GithubActionPipelineTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.path = self.root / ".github" / "workflows" / "data-pipeline.yml"
        self.text = self.path.read_text(encoding="utf-8")

    def test_supports_schedule_and_manual_validation_without_push_trigger(self):
        self.assertRegex(self.text, r"(?m)^\s{2}schedule:\s*$")
        self.assertRegex(self.text, r"(?m)^\s{2}workflow_dispatch:\s*$")
        self.assertNotRegex(self.text, r"(?m)^\s{2}push:\s*$")
        self.assertRegex(
            self.text,
            r"(?s)workflow_dispatch:.*?publish:.*?default:\s*false.*?type:\s*boolean",
        )

    def test_runs_the_public_strict_main_flow(self):
        self.assertIn("python -m service.data_package.cli build --strict", self.text)
        self.assertIn("DATA_PACKAGE_STRICT: '1'", self.text)
        self.assertIn("VALIDATION_STRICT: '1'", self.text)
        self.assertIn("service.data_package.validation.cli validate", self.text)
        self.assertIn("npm pack --dry-run", self.text)

    def test_never_pushes_generated_files_to_main(self):
        normalized = re.sub(r"\\\n\s*", " ", self.text)
        self.assertNotRegex(normalized, r"git push[^\n]*refs/heads/main")
        self.assertNotIn("git push origin HEAD:main", normalized)
        self.assertIn("refs/heads/online", self.text)
        self.assertIn("--force-with-lease=refs/heads/online", self.text)

    def test_external_writes_are_explicit_and_scoped(self):
        self.assertIn("github.event_name == 'schedule' || inputs.publish == true", self.text)
        self.assertGreaterEqual(
            self.text.count("NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}"), 2
        )
        self.assertIn("Repository secret NPM_TOKEN is required before publishing.", self.text)
        self.assertIn("package-manager-cache: false", self.text)
        self.assertRegex(
            self.text,
            r"(?s)jobs:.*?update-and-publish:.*?permissions:\s*\n\s{6}contents:\s*write",
        )

    def test_online_state_keeps_release_resume_metadata(self):
        self.assertIn("for RELEASE_FILE in CHANGELOG.md RELEASES.json", self.text)
        self.assertIn('> "packages/kancolle-data/$RELEASE_FILE"', self.text)
        self.assertIn(".generated-state/reports/verification-report.json", self.text)
        self.assertIn('git cat-file -e "refs/remotes/origin/online:packages/kancolle-data/$RELEASE_FILE"', self.text)


if __name__ == "__main__":
    unittest.main()
