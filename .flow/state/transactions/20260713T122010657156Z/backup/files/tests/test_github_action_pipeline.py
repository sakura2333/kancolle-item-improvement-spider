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



    @staticmethod
    def _workflow_run_blocks(text: str) -> list[str]:
        lines = text.splitlines()
        blocks: list[str] = []
        index = 0
        while index < len(lines):
            match = re.match(r"^(?P<indent>\s*)run:\s*\|\s*$", lines[index])
            if match is None:
                index += 1
                continue
            base_indent = len(match.group("indent"))
            content_indent = base_indent + 2
            index += 1
            block: list[str] = []
            while index < len(lines):
                line = lines[index]
                if line.strip():
                    indentation = len(line) - len(line.lstrip(" "))
                    if indentation <= base_indent:
                        break
                    if indentation < content_indent:
                        raise AssertionError(f"invalid YAML run indentation: {line!r}")
                    block.append(line[content_indent:])
                else:
                    block.append("")
                index += 1
            blocks.append("\n".join(block) + "\n")
        return blocks

    @staticmethod
    def _normalize_github_expressions(script: str) -> str:
        return re.sub(r"\$\{\{.*?\}\}", "VALUE", script, flags=re.S)

    def _step_python(self, step_name: str, next_step_name: str) -> str:
        section = self.build.split(f"- name: {step_name}", 1)[1].split(
            f"- name: {next_step_name}", 1
        )[0]
        match = re.search(r"python3 - <<'PY'\n(?P<body>.*?)\n\s+PY", section, re.S)
        self.assertIsNotNone(match, f"missing inline Python for {step_name}")
        return textwrap.dedent(match.group("body"))

    def _run_stateless_plan(
        self,
        *,
        current_digest: str,
        online_digest: str | None,
        online_version: str,
        current_improvement2_digest: str | None = None,
        online_improvement2_digest: str | None = None,
        current_business_digest: str | None = None,
        current_improvement2_business_digest: str | None = None,
        head_version: str | None,
        head_digest: str | None,
        head_business_digest: str | None = None,
        latest_tag: str | None = None,
        improvement2_exists: bool = True,
        improvement2_digest: str | None = None,
        improvement2_business_digest: str | None = None,
        improvement2_tag: str | None = None,
        published_versions: list[str] | None = None,
        repository_version: str = "0.5.6",
    ) -> tuple[subprocess.CompletedProcess[str], dict | None]:
        script = self._step_python(
            "Plan stateless publication target",
            "Prepare frozen release projection",
        )
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            current = root / "current.json"
            npm_business = root / "npm-business.json"
            online = root / "online.json"
            registry = root / "registry.json"
            versions = root / "versions.json"
            plan = root / "plan.json"
            package_dir = root / "packages/kancolle-data"
            package_dir.mkdir(parents=True)
            (package_dir / "package.json").write_text(
                json.dumps({"name": "@sakura2333/kancolle-data", "version": repository_version}),
                encoding="utf-8",
            )
            current_improvement2_digest = (
                current_improvement2_digest or "d" * 64
            )
            current_business_digest = current_business_digest or current_digest
            current_improvement2_business_digest = (
                current_improvement2_business_digest or current_improvement2_digest
            )
            if online_improvement2_digest is None and online_digest is not None:
                online_improvement2_digest = current_improvement2_digest
            current.write_text(
                json.dumps(
                    {
                        "identitySchemaVersion": 2,
                        "contentDigest": current_digest,
                        "improvement2ContentDigest": current_improvement2_digest,
                    }
                ),
                encoding="utf-8",
            )
            npm_business.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "npmBusinessIdentities": {
                            "schemaVersion": 1,
                            "current": current_business_digest,
                            "improvement2": current_improvement2_business_digest,
                        },
                    }
                ),
                encoding="utf-8",
            )
            online.write_text(
                json.dumps(
                    {
                        "contentDigest": online_digest,
                        "improvement2ContentDigest": online_improvement2_digest,
                    }
                ),
                encoding="utf-8",
            )
            head = None
            if head_version is not None:
                compat = f"{head_version}-improvement2"
                resolved_improvement2_digest = (
                    improvement2_digest
                    if improvement2_digest is not None
                    else (current_improvement2_digest if improvement2_exists else None)
                )
                head = {
                    "version": head_version,
                    "contentDigest": head_digest,
                    "npmBusinessDigest": head_business_digest or head_digest,
                    "latestTag": latest_tag if latest_tag is not None else head_version,
                    "improvement2Version": compat,
                    "improvement2Exists": improvement2_exists,
                    "improvement2ContentDigest": resolved_improvement2_digest,
                    "improvement2NpmBusinessDigest": (
                        improvement2_business_digest
                        if improvement2_business_digest is not None
                        else resolved_improvement2_digest
                    ),
                    "improvement2Tag": (
                        improvement2_tag if improvement2_tag is not None else compat
                    ),
                }
            registry.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "package": "@sakura2333/kancolle-data",
                        "versions": published_versions or [],
                        "distTags": {},
                        "head": head,
                    }
                ),
                encoding="utf-8",
            )
            versions.write_text(json.dumps(published_versions or []), encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "CURRENT_SNAPSHOT": str(current),
                    "CURRENT_NPM_BUSINESS": str(npm_business),
                    "ONLINE_SNAPSHOT": str(online),
                    "ONLINE_VERSION": online_version,
                    "REGISTRY_STATE": str(registry),
                    "PUBLISHED_VERSIONS": str(versions),
                    "PLAN": str(plan),
                }
            )
            completed = subprocess.run(
                [sys.executable, "-c", script],
                text=True,
                capture_output=True,
                check=False,
                env=env,
                cwd=root,
            )
            payload = json.loads(plan.read_text(encoding="utf-8")) if plan.is_file() else None
            return completed, payload


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
        self.assertIn("name: Restore current release controller", compute_job)
        self.assertIn('git checkout -f --detach "$GITHUB_SHA"', compute_job)
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
        self.assertIn("npm whoami --registry https://registry.npmjs.org/", publish_job)
        self.assertIn("needs.build.outputs.should_publish == 'true'", publish_job)
        self.assertLess(
            self.build.index("- name: Verify frozen build candidate"),
            self.build.index("- name: Upload build candidate"),
        )
        self.assertLess(
            self.build.index("- name: Upload build candidate"),
            self.build.index("- name: Publish or reconcile frozen npm variants"),
        )

    def test_build_rejects_untrusted_requested_source_runs_and_plans_from_registry(self):
        self.assertIn("requested source_run_id is not a recent successful main run", self.build)
        self.assertIn("name: Plan stateless publication target", self.build)
        self.assertNotIn("name: Guard publication reconciliation", self.build)
        self.assertNotIn("previously uploaded Build Candidate", self.build)
        self.assertNotIn("online state is missing", self.build)

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
        self.assertIn("npm whoami --registry https://registry.npmjs.org/", self.release)


    def test_registry_head_consumer_digest_is_read_before_stateless_planning(self):
        inspect_index = self.build.index("- name: Inspect current npm business content")
        registry_index = self.build.index("- name: Read authoritative npm data state")
        plan_index = self.build.index("- name: Plan stateless publication target")
        prepare_index = self.build.index("- name: Prepare frozen release projection")
        self.assertLess(inspect_index, registry_index)
        self.assertLess(registry_index, plan_index)
        self.assertLess(plan_index, prepare_index)
        registry = self.build[registry_index:plan_index]
        self.assertIn("npm pack", registry)
        self.assertIn("package/RELEASES.json", registry)
        self.assertIn("package/CHANGELOG.md", registry)
        self.assertIn("improvement2ContentDigest", registry)
        self.assertIn("inspect_consumer_tarball", registry)
        self.assertIn("inspect_npm_business_tarball", registry)
        self.assertIn("CURRENT_VARIANT", registry)
        self.assertIn("IMPROVEMENT2_VARIANT", registry)
        self.assertIn("contentDigest", registry)
        self.assertIn("npmBusinessDigest", registry)
        self.assertIn("range(3)", registry)
        self.assertIn("npm_release_set inspect-business", self.build)
        self.assertIn('plan["consumerContentDigest"]', self.build)
        self.assertIn('plan["improvement2ConsumerContentDigest"]', self.build)
        self.assertIn('plan["npmBusinessIdentities"]', self.build)
        self.assertIn('plan["registryState"]', self.build)

    def test_same_consumer_digest_reuses_registry_head_and_reconciles_automatically(self):
        digest = "a" * 64
        completed, plan = self._run_stateless_plan(
            current_digest=digest,
            online_digest="b" * 64,
            online_version="0.5.6",
            head_version="0.5.10",
            head_digest=digest,
            published_versions=["0.5.10"],
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(plan["version"], "0.5.10")
        self.assertTrue(plan["shouldPublish"])
        self.assertFalse(plan["allocatedNewVersion"])
        self.assertEqual(plan["mode"], "reconcile-existing-content")
        self.assertEqual(
            plan["reason"], "reconcile-already-published-npm-business-content"
        )

    def test_same_consumer_digest_is_noop_when_registry_tags_and_online_are_aligned(self):
        digest = "a" * 64
        completed, plan = self._run_stateless_plan(
            current_digest=digest,
            online_digest=digest,
            online_version="0.5.10",
            head_version="0.5.10",
            head_digest=digest,
            published_versions=["0.5.10", "0.5.10-improvement2"],
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(plan["shouldPublish"])
        self.assertEqual(plan["version"], "0.5.10")
        self.assertEqual(plan["mode"], "noop")

    def test_existing_improvement2_business_change_allocates_new_patch(self):
        digest = "a" * 64
        completed, plan = self._run_stateless_plan(
            current_digest=digest,
            online_digest=digest,
            online_version="0.5.10",
            head_version="0.5.10",
            head_digest=digest,
            current_improvement2_digest="c" * 64,
            online_improvement2_digest="c" * 64,
            current_improvement2_business_digest="e" * 64,
            improvement2_exists=True,
            improvement2_digest="b" * 64,
            improvement2_business_digest="d" * 64,
            published_versions=["0.5.10", "0.5.10-improvement2"],
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(plan["version"], "0.5.11")
        self.assertTrue(plan["allocatedNewVersion"])
        self.assertEqual(plan["mode"], "publish-new-content")

    def test_existing_improvement2_digest_match_can_noop(self):
        digest = "a" * 64
        completed, plan = self._run_stateless_plan(
            current_digest=digest,
            online_digest=digest,
            online_version="0.5.10",
            head_version="0.5.10",
            head_digest=digest,
            current_improvement2_digest="c" * 64,
            online_improvement2_digest="c" * 64,
            improvement2_exists=True,
            improvement2_digest="c" * 64,
            published_versions=["0.5.10", "0.5.10-improvement2"],
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(plan["shouldPublish"])
        self.assertEqual(plan["mode"], "noop")

    def test_missing_improvement2_variant_reconciles_without_allocating_patch(self):
        digest = "a" * 64
        completed, plan = self._run_stateless_plan(
            current_digest=digest,
            online_digest=digest,
            online_version="0.5.10",
            head_version="0.5.10",
            head_digest=digest,
            improvement2_exists=False,
            improvement2_tag="0.5.9-improvement2",
            published_versions=["0.5.10"],
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(plan["shouldPublish"])
        self.assertEqual(plan["version"], "0.5.10")
        self.assertFalse(plan["allocatedNewVersion"])

    def test_registry_without_online_is_reconciled_automatically_for_same_digest(self):
        digest = "a" * 64
        completed, plan = self._run_stateless_plan(
            current_digest=digest,
            online_digest=None,
            online_version="",
            head_version="0.5.10",
            head_digest=digest,
            published_versions=["0.5.10", "0.5.10-improvement2"],
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(plan["shouldPublish"])
        self.assertEqual(plan["version"], "0.5.10")
        self.assertEqual(plan["mode"], "reconcile-existing-content")

    def test_new_npm_business_content_allocates_next_patch_from_registry_only(self):
        completed, plan = self._run_stateless_plan(
            current_digest="c" * 64,
            online_digest="c" * 64,
            online_version="0.5.10",
            head_version="0.5.10",
            head_digest="b" * 64,
            published_versions=["0.5.10", "0.5.10-improvement2"],
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(plan["version"], "0.5.11")
        self.assertTrue(plan["shouldPublish"])
        self.assertTrue(plan["allocatedNewVersion"])
        self.assertEqual(plan["mode"], "publish-new-content")

    def test_contract_only_change_allocates_new_patch_when_data_is_unchanged(self):
        digest = "a" * 64
        completed, plan = self._run_stateless_plan(
            current_digest=digest,
            online_digest=digest,
            online_version="0.5.10",
            current_business_digest="c" * 64,
            head_version="0.5.10",
            head_digest=digest,
            head_business_digest="b" * 64,
            published_versions=["0.5.10", "0.5.10-improvement2"],
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(plan["version"], "0.5.11")
        self.assertTrue(plan["allocatedNewVersion"])
        self.assertEqual(plan["reason"], "publish-new-npm-business-content")

    def test_reconciliation_hydrates_existing_registry_tarballs_into_candidate(self):
        prepare = self.build.split("- name: Prepare frozen release projection", 1)[1].split(
            "- name: Freeze immutable build candidate", 1
        )[0]
        self.assertIn("PUBLICATION_MODE", prepare)
        self.assertIn("reconcile-existing-content", prepare)
        self.assertIn("npm_release_set hydrate-published", prepare)
        self.assertIn("--published-versions", prepare)
        self.assertIn("npm_release_set verify", prepare)
        self.assertNotIn("npm pack", prepare)
        self.assertNotIn("python3 - <<'PY'", prepare)

    def test_every_public_workflow_run_block_is_valid_bash(self):
        workflows = {
            "source-acquire.yml": self.acquire,
            "data-build.yml": self.build,
            "release.yml": self.release,
        }
        checked = 0
        for workflow, text in workflows.items():
            blocks = self._workflow_run_blocks(text)
            self.assertTrue(blocks, f"{workflow} has no run blocks")
            for block_index, script in enumerate(blocks, start=1):
                normalized = self._normalize_github_expressions(script)
                completed = subprocess.run(
                    ["bash", "-n"],
                    input=normalized,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    f"{workflow} run block {block_index} is invalid:\n"
                    f"{completed.stderr}\n--- script ---\n{normalized}",
                )
                checked += 1
        self.assertGreater(checked, 0)

    def test_online_history_is_not_used_as_npm_release_authority(self):
        baseline = self.build.split("- name: Load previous online baseline", 1)[1].split(
            "- name: Build from frozen source bundle", 1
        )[0]
        self.assertNotIn("packages/kancolle-data/RELEASES.json", baseline)
        self.assertNotIn("packages/kancolle-data/CHANGELOG.md", baseline)
        prepare = self.build.split("- name: Prepare frozen release projection", 1)[1]
        self.assertIn("REGISTRY_HISTORY", prepare)
        self.assertIn("npm-registry-history", self.build)


if __name__ == "__main__":
    unittest.main()
