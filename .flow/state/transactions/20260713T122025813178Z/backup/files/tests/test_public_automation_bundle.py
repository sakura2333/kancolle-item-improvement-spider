from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.acquire.cli import (
    _REQUIRED_BUILD_CACHE_SOURCES,
    acquire_non_wikiwiki_sources,
    verify_build_cache_closure,
)
from automation.compute.cli import _trust_frozen_source_bundle, freeze, restore_source_bundle
from automation.common.bundle import (
    BundleError,
    verify_manifest,
    verify_ready_lock,
    write_manifest,
    write_ready_lock,
)
from automation.release.cli import verify as verify_release_candidate
from service.data_package.acquisition_references import QUEST_DATA_URL


class PublicAutomationBundleTest(unittest.TestCase):
    def tearDown(self):
        from util.http_cache import audit

        audit.reset_fetch_audit()
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


    def test_source_bundle_ready_lock_binds_manifest_and_rejects_extra_authority(self):
        with tempfile.TemporaryDirectory() as temp_name:
            bundle = Path(temp_name) / "source-bundle"
            bundle.mkdir()
            (bundle / "raw.txt").write_text("evidence\n", encoding="utf-8")
            manifest = write_manifest(
                bundle,
                kind="source-bundle",
                project_id="kancolle-item-improvement-spider",
                commit="a" * 40,
            )
            lock = write_ready_lock(bundle, manifest)
            self.assertEqual(
                verify_ready_lock(bundle, verify_manifest(bundle, expected_kind="source-bundle")),
                lock,
            )
            payload = json.loads((bundle / "source-bundle.lock.json").read_text(encoding="utf-8"))
            payload["contentHash"] = "sha256:" + "0" * 64
            (bundle / "source-bundle.lock.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(BundleError, "ready lock mismatch"):
                verify_ready_lock(bundle, manifest)

            write_ready_lock(bundle, manifest)
            payload = json.loads((bundle / "source-bundle.lock.json").read_text(encoding="utf-8"))
            payload["collections"] = ["akashi-list", "invented-trust-grant"]
            (bundle / "source-bundle.lock.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(BundleError, "ready lock fields are invalid"):
                verify_ready_lock(bundle, manifest)

    def test_verified_source_bundle_restores_process_audit_state(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root, commit = self._repo(Path(temp_name))
            bundle = Path(temp_name) / "source-bundle"
            cache = bundle / ".spider/local/source-cache/example.test"
            cache.mkdir(parents=True)
            cached = cache / "data.json"
            cached.write_text("{}\n", encoding="utf-8")
            meta = bundle / ".spider/local/source-cache/_meta.json"
            meta.parent.mkdir(parents=True, exist_ok=True)
            meta.write_text(
                json.dumps(
                    {
                        "example.test/data.json": {
                            "url": "https://example.test/data.json",
                            "fetch_status": "fresh",
                            "used_cache_fallback": False,
                        }
                    }
                ),
                encoding="utf-8",
            )
            manifest = write_manifest(
                bundle,
                kind="source-bundle",
                project_id="kancolle-item-improvement-spider",
                commit=commit,
            )
            write_ready_lock(bundle, manifest)

            source = restore_source_bundle(root, bundle)
            _trust_frozen_source_bundle(root, source)

            from util.http_cache import audit

            self.assertTrue(audit.was_validated_in_run("https://example.test/data.json"))
            self.assertTrue(audit.collection_completed_in_run("akashi-list"))


    def test_acquire_prefetches_kcquests_as_a_required_build_input(self):
        with (
            patch("automation.acquire.cli.update_start2_if_needed"),
            patch(
                "automation.acquire.cli.collect_akashi_source_records",
                return_value=[{"equipmentId": 1}],
            ),
            patch("automation.acquire.cli.prefetch_source") as prefetch,
        ):
            statuses = acquire_non_wikiwiki_sources()

        requested = [call.args[0] for call in prefetch.call_args_list]
        self.assertIn(QUEST_DATA_URL, requested)
        self.assertEqual(statuses["kcquests-catalog"], "ready")

    def test_ready_lock_cache_closure_covers_every_fixed_strict_build_input(self):
        expected_urls = [url for _name, url in _REQUIRED_BUILD_CACHE_SOURCES]
        self.assertIn(QUEST_DATA_URL, expected_urls)
        with (
            patch(
                "automation.acquire.cli.storage.url_to_path",
                side_effect=lambda url: f"/cache/{expected_urls.index(url)}",
            ),
            patch("automation.acquire.cli.storage.require_cached_file") as require_cached,
            patch(
                "automation.acquire.cli.storage.load_meta",
                side_effect=lambda path: {
                    "url": expected_urls[int(path.rsplit("/", 1)[1])],
                    "fetch_status": "fresh",
                    "used_cache_fallback": False,
                },
            ),
            patch(
                "automation.acquire.cli.storage.cache_key",
                side_effect=lambda path: path.removeprefix("/cache/"),
            ),
        ):
            ready = verify_build_cache_closure()

        self.assertEqual(set(ready), {name for name, _url in _REQUIRED_BUILD_CACHE_SOURCES})
        self.assertEqual(
            [call.args[1] for call in require_cached.call_args_list],
            expected_urls,
        )

    def test_ready_lock_cache_closure_rejects_fallback_metadata(self):
        with (
            patch("automation.acquire.cli.storage.url_to_path", return_value="/cache/input"),
            patch("automation.acquire.cli.storage.require_cached_file"),
            patch(
                "automation.acquire.cli.storage.load_meta",
                return_value={
                    "url": _REQUIRED_BUILD_CACHE_SOURCES[0][1],
                    "fetch_status": "stale",
                    "used_cache_fallback": True,
                },
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "not freshly validated"):
                verify_build_cache_closure()

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
