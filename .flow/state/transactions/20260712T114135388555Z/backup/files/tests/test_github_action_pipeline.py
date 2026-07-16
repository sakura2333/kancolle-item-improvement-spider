from __future__ import annotations

import unittest
from pathlib import Path


class GithubActionPipelineTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        workflow_root = self.root / ".github/workflows"
        self.acquire = (workflow_root / "source-acquire.yml").read_text(encoding="utf-8")
        self.build = (workflow_root / "data-build.yml").read_text(encoding="utf-8")
        self.release = (workflow_root / "release.yml").read_text(encoding="utf-8")

    def test_pipeline_is_split_into_acquire_build_and_release(self):
        self.assertIn("name: Acquire Spider Sources", self.acquire)
        self.assertIn("name: Build Data Candidate", self.build)
        self.assertIn("name: Release Data Candidate", self.release)
        self.assertFalse((self.root / ".github/workflows/data-pipeline.yml").exists())

    def test_all_workflows_use_python_314_and_locked_uv(self):
        for text in (self.acquire, self.build, self.release):
            self.assertIn("jdx/mise-action@v4.2.0", text)
            self.assertIn("mise exec -- uv sync --locked", text)
            self.assertNotIn("astral-sh/setup-uv", text)
            self.assertNotIn("pip install -r", text)

    def test_public_workflows_do_not_depend_on_dev_flow(self):
        for text in (self.acquire, self.build, self.release):
            self.assertNotIn("./flow", text)
            self.assertNotIn("script/", text)
            self.assertNotIn("tools/", text)
            self.assertNotIn(".flow/", text)

    def test_acquire_and_build_use_daily_offset_schedules_and_global_source_lock(self):
        self.assertIn("cron: '17 18 * * *'", self.acquire)
        self.assertIn("START2_CACHE_MAX_AGE_HOURS: '24'", self.acquire)
        self.assertIn("previous-source-bundle", self.acquire)
        self.assertIn("--seed-bundle", self.acquire)
        self.assertIn("cron: '17 6 * * *'", self.build)
        self.assertNotIn("workflow_run:", self.build)
        self.assertIn("source-acquire-lock-timeout", self.build)
        self.assertIn("range(21)", self.build)
        self.assertIn("time.sleep(15)", self.build)
        self.assertIn("The next daily run will retry", self.build)

    def test_acquire_only_outputs_a_source_bundle(self):
        self.assertIn("python -m automation.acquire.cli", self.acquire)
        self.assertIn("name: kancolle-source-bundle", self.acquire)
        self.assertNotIn("npm publish", self.acquire)
        self.assertNotIn("contents: write", self.acquire)

    def test_artifact_uploads_preserve_hidden_runtime_state(self):
        acquire_upload = self.acquire.split("- name: Upload source bundle", 1)[1]
        build_upload = self.build.split("- name: Upload build candidate", 1)[1]
        self.assertIn("include-hidden-files: true", acquire_upload)
        self.assertIn("include-hidden-files: true", build_upload)
        self.assertLess(
            acquire_upload.index("include-hidden-files: true"),
            acquire_upload.index("if-no-files-found: error"),
        )
        self.assertLess(
            build_upload.index("include-hidden-files: true"),
            build_upload.index("if-no-files-found: error"),
        )

    def test_build_consumes_source_and_outputs_frozen_candidate(self):
        self.assertIn("name: kancolle-source-bundle", self.build)
        self.assertIn("python -m automation.compute.cli prepare", self.build)
        self.assertIn("python -m automation.compute.cli freeze", self.build)
        self.assertIn("python -m automation.release.npm_release_set build", self.build)
        self.assertIn("name: kancolle-build-candidate", self.build)
        self.assertNotIn("npm publish", self.build)
        self.assertNotIn("git push", self.build)
        self.assertNotIn("contents: write", self.build)

    def test_release_only_consumes_frozen_candidate(self):
        self.assertIn("name: kancolle-build-candidate", self.release)
        self.assertIn("python -m automation.release.cli", self.release)
        self.assertIn("python -m automation.release.npm_release_set verify", self.release)
        self.assertIn("python -m automation.release.npm_publish", self.release)
        self.assertIn("refs/heads/online", self.release)
        self.assertIn("contents: write", self.release)
        self.assertNotIn("automation.acquire", self.release)
        self.assertNotIn("automation.compute.cli prepare", self.release)
        self.assertIn("NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}", self.release)


if __name__ == "__main__":
    unittest.main()
