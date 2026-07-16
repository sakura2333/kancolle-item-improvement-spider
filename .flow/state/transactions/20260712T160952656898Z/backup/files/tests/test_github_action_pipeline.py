from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


class GithubActionPipelineTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        workflow_root = self.root / ".github/workflows"
        self.acquire = (workflow_root / "source-acquire.yml").read_text(encoding="utf-8")
        self.build = (workflow_root / "data-build.yml").read_text(encoding="utf-8")
        self.release = (workflow_root / "release.yml").read_text(encoding="utf-8")


    def _step_python(self, step_name: str, next_step_name: str) -> str:
        section = self.build.split(f"- name: {step_name}", 1)[1].split(
            f"- name: {next_step_name}", 1
        )[0]
        match = re.search(r"python3 - <<'PY'\n(?P<body>.*?)\n\s+PY", section, re.S)
        self.assertIsNotNone(match, f"missing inline Python for {step_name}")
        return textwrap.dedent(match.group("body"))

    def _run_reconciliation_guard(
        self,
        *,
        current_digest: str,
        online_digest: str | None,
        online_version: str,
        head_version: str | None,
        head_digest: str | None,
        changed: bool,
    ) -> subprocess.CompletedProcess[str]:
        script = self._step_python(
            "Guard publication reconciliation",
            "Plan package version",
        )
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            current = root / "current.json"
            online = root / "online.json"
            head = root / "head.json"
            current.write_text(json.dumps({"contentDigest": current_digest}), encoding="utf-8")
            online.write_text(json.dumps({"contentDigest": online_digest}), encoding="utf-8")
            head.write_text(
                json.dumps({"version": head_version, "contentDigest": head_digest}),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.update(
                {
                    "DATA_CHANGED": str(changed).lower(),
                    "CURRENT_SNAPSHOT": str(current),
                    "ONLINE_SNAPSHOT": str(online),
                    "ONLINE_VERSION": online_version,
                    "REGISTRY_HEAD_PATH": str(head),
                }
            )
            return subprocess.run(
                [sys.executable, "-c", script],
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )

    def test_pipeline_is_split_into_acquire_build_and_recovery_release(self):
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

    def test_build_consumes_source_freezes_candidate_and_publishes_automatically(self):
        compute_job = self.build.split("\n  build:\n", 1)[1].split("\n  publish:\n", 1)[0]
        publish_job = self.build.split("\n  publish:\n", 1)[1]
        self.assertIn("name: kancolle-source-bundle", compute_job)
        self.assertIn("python -m automation.compute.cli prepare", compute_job)
        self.assertIn("python -m automation.compute.cli freeze", compute_job)
        self.assertIn("python -m automation.release.npm_release_set build", compute_job)
        self.assertIn("python -m automation.release.cli", compute_job)
        self.assertIn("name: kancolle-build-candidate", compute_job)
        self.assertNotIn("NPM_TOKEN", compute_job)
        self.assertNotIn("contents: write", compute_job)
        self.assertIn("python -m automation.release.npm_publish", publish_job)
        self.assertIn("refs/heads/online", publish_job)
        self.assertIn("contents: write", publish_job)
        self.assertIn("NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}", publish_job)
        self.assertIn("needs.build.outputs.should_publish == 'true'", publish_job)
        self.assertLess(
            self.build.index("- name: Verify frozen build candidate"),
            self.build.index("- name: Upload build candidate"),
        )
        self.assertLess(
            self.build.index("- name: Upload build candidate"),
            self.build.index("- name: Publish or reconcile frozen npm variants"),
        )

    def test_build_rejects_untrusted_requested_source_runs_and_guards_reconciliation(self):
        self.assertIn("requested source_run_id is not a recent successful main run", self.build)
        self.assertIn("name: Guard publication reconciliation", self.build)
        self.assertIn("npm publication is ahead of online state", self.build)
        self.assertNotIn("--online-version", self.build)

    def test_build_and_manual_release_share_one_publication_lock(self):
        self.assertIn("group: kancolle-data-publication", self.build)
        self.assertIn("group: kancolle-data-publication", self.release)

    def test_release_only_consumes_frozen_candidate_for_recovery(self):
        self.assertIn("name: kancolle-build-candidate", self.release)
        self.assertIn("python -m automation.release.cli", self.release)
        self.assertIn("python -m automation.release.npm_release_set verify", self.release)
        self.assertIn("python -m automation.release.npm_publish", self.release)
        self.assertIn("refs/heads/online", self.release)
        self.assertIn("contents: write", self.release)
        self.assertNotIn("automation.acquire", self.release)
        self.assertNotIn("automation.compute.cli prepare", self.release)
        self.assertIn("NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}", self.release)

    def test_registry_head_consumer_digest_is_read_before_version_planning(self):
        registry_index = self.build.index("- name: Read npm registry state")
        guard_index = self.build.index("- name: Guard publication reconciliation")
        plan_index = self.build.index("- name: Plan package version")
        self.assertLess(registry_index, guard_index)
        self.assertLess(guard_index, plan_index)
        registry = self.build[registry_index:guard_index]
        self.assertIn("npm pack", registry)
        self.assertIn("package/RELEASES.json", registry)
        self.assertIn("contentDigest", registry)
        self.assertIn("range(3)", registry)
        self.assertIn('plan["consumerContentDigest"]', self.build)
        self.assertIn('plan["registryHead"]', self.build)

    def test_same_consumer_digest_cannot_allocate_another_patch_version(self):
        digest = "a" * 64
        completed = self._run_reconciliation_guard(
            current_digest=digest,
            online_digest="b" * 64,
            online_version="0.5.6",
            head_version="0.5.7",
            head_digest=digest,
            changed=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("already published as 0.5.7", completed.stderr)
        self.assertIn("previously uploaded Build Candidate", completed.stderr)

    def test_new_consumer_digest_can_continue_to_version_planning(self):
        completed = self._run_reconciliation_guard(
            current_digest="c" * 64,
            online_digest="b" * 64,
            online_version="0.5.6",
            head_version="0.5.6",
            head_digest="b" * 64,
            changed=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_registry_without_online_requires_explicit_recovery(self):
        completed = self._run_reconciliation_guard(
            current_digest="c" * 64,
            online_digest=None,
            online_version="",
            head_version="0.5.8",
            head_digest="b" * 64,
            changed=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("online state is missing", completed.stderr)


if __name__ == "__main__":
    unittest.main()
