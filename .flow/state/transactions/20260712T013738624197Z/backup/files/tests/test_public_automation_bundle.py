from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from automation.compute.cli import freeze
from automation.common.bundle import BundleError, verify_manifest, write_manifest
from automation.release.cli import verify as verify_release_candidate


class PublicAutomationBundleTest(unittest.TestCase):
    def _repo(self, base: Path) -> tuple[Path, str]:
        root = base / "repo"
        root.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
        (root / "README.md").write_text("test\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        return root, commit

    def test_source_bundle_manifest_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name) / "source"
            root.mkdir()
            (root / "raw.txt").write_text("evidence\n", encoding="utf-8")
            write_manifest(
                root,
                kind="source-bundle",
                project_id="kancolle-item-improvement-spider",
                commit="a" * 40,
            )
            verify_manifest(root, expected_kind="source-bundle")
            (root / "raw.txt").write_text("changed\n", encoding="utf-8")
            with self.assertRaises(BundleError):
                verify_manifest(root, expected_kind="source-bundle")

    def test_non_publish_candidate_is_bound_to_source_manifest_and_commit(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root, commit = self._repo(Path(temp_name))
            package_dir = root / "dist/packages/kancolle-data"
            package_dir.mkdir(parents=True)
            (package_dir / "package.json").write_text(
                json.dumps({"name": "@sakura2333/kancolle-data", "version": "0.5.1"}),
                encoding="utf-8",
            )
            (package_dir / "manifest.json").write_text(
                json.dumps({"packageVersion": "0.5.1"}), encoding="utf-8"
            )
            data_dir = root / "dist/data-pipeline"
            data_dir.mkdir(parents=True)
            (data_dir / "result.json").write_text("{}\n", encoding="utf-8")

            source_dir = Path(temp_name) / "source-bundle"
            source_dir.mkdir()
            (source_dir / "raw.txt").write_text("evidence\n", encoding="utf-8")
            source_manifest = write_manifest(
                source_dir,
                kind="source-bundle",
                project_id="kancolle-item-improvement-spider",
                commit=commit,
            )
            release_plan = Path(temp_name) / "release-plan.json"
            release_plan.write_text(
                json.dumps({"shouldPublish": False, "version": None}), encoding="utf-8"
            )
            verification = Path(temp_name) / "verification-report.json"
            verification.write_text(json.dumps({"contentDigest": "test"}), encoding="utf-8")
            candidate = Path(temp_name) / "candidate"
            freeze(
                root,
                candidate,
                source_manifest=source_manifest,
                release_plan=release_plan,
                verification_report=verification,
            )

            result = verify_release_candidate(root, candidate)
            self.assertFalse(result["publication"]["shouldPublish"])
            self.assertEqual(result["candidate"]["commit"], commit)
            self.assertEqual(
                result["candidate"]["metadata"]["sourceBundleContentHash"],
                source_manifest["contentHash"],
            )

            frozen_source = candidate / "source-bundle-manifest.json"
            payload = json.loads(frozen_source.read_text(encoding="utf-8"))
            payload["contentHash"] = "sha256:" + "0" * 64
            frozen_source.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises((BundleError, RuntimeError)):
                verify_release_candidate(root, candidate)


if __name__ == "__main__":
    unittest.main()
