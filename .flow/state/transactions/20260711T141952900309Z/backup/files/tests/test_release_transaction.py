from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from script.project import main_release, stable_command
from script.project.release_transaction import ReleaseTransaction, ReleaseTransactionError


class ReleaseTransactionTest(unittest.TestCase):
    def test_candidate_freeze_is_one_way_and_workspace_is_removed(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            transaction = ReleaseTransaction(root / "tx", "1.0.0-deadbeef")
            candidate = transaction.prepare_build()
            (candidate / "README.md").write_text("public\n", encoding="utf-8")
            archive = transaction.workspace / "candidate.zip"
            stable_command._write_candidate_archive(candidate, archive)
            records = stable_command._candidate_records(candidate)
            manifest = {
                "schemaVersion": 8,
                "releaseId": transaction.release_id,
                "candidateContentSha256": stable_command._candidate_hash(records),
                "candidateArchiveSha256": stable_command._sha256(archive),
                "files": records,
            }
            transaction.freeze_candidate(manifest=manifest, archive_source=archive)

            self.assertFalse(transaction.workspace.exists())
            self.assertTrue(transaction.candidate_public.is_dir())
            self.assertTrue(transaction.candidate_archive.is_file())
            self.assertEqual(transaction.load_manifest(), manifest)
            self.assertEqual(transaction.load_status()["state"], "candidate-frozen")
            with self.assertRaises(ReleaseTransactionError):
                transaction.prepare_build()

    def test_review_bundle_is_fixed_projection_not_sanitized_internal_receipt(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            transaction = ReleaseTransaction(root / "tx", "1.0.0-deadbeef")
            transaction.candidate_public.mkdir(parents=True)
            public_manifest = {
                "schemaVersion": 2,
                "project": "demo",
                "version": "1.0.0",
                "sourceCommit": "a" * 40,
                "managedFiles": ["PUBLIC-CONTENT-MANIFEST.json", "README.md"],
            }
            (transaction.candidate_public / "README.md").write_text("public\n", encoding="utf-8")
            (transaction.candidate_public / "PUBLIC-CONTENT-MANIFEST.json").write_text(
                json.dumps(public_manifest) + "\n", encoding="utf-8"
            )
            stable_command._write_candidate_archive(
                transaction.candidate_public, transaction.candidate_archive
            )
            records = stable_command._candidate_records(transaction.candidate_public)
            manifest = {
                "schemaVersion": 8,
                "releaseId": transaction.release_id,
                "project": "demo",
                "version": "1.0.0",
                "sourceCommit": "a" * 40,
                "sourceTree": "b" * 40,
                "candidateContentSha256": stable_command._candidate_hash(records),
                "candidateArchiveSha256": stable_command._sha256(transaction.candidate_archive),
                "files": records,
                "contentManifest": public_manifest,
                "publicContentPolicy": "project-content-registry-public-snapshot",
                "publicContentAudit": {
                    "findingCount": 0,
                    "publicIsolation": {
                        "internalPathCount": 0,
                        "internalReferenceCount": 0,
                        "absolutePathCount": 0,
                        "exceptionCount": 1,
                        "exceptionManifestSha256": "c" * 64,
                        "exceptions": ["policy-rule"],
                    },
                },
            }
            config = {
                "stable": {
                    "categories": {
                        "documentation": ["README.md", "PUBLIC-CONTENT-MANIFEST.json"]
                    },
                    "publicExceptions": {
                        "schemaVersion": 1,
                        "projectId": "demo",
                        "policy": "deny-by-default-explicit-public-exceptions",
                        "exceptions": [
                            {
                                "id": "policy-rule",
                                "reason": "Review policy literals are evidence, not leaked values.",
                                "owner": "release",
                                "review": "mechanical-and-ai",
                                "matches": [],
                                "reviewFiles": ["README.md"],
                                "forbiddenContent": ["/Users/", "workspaceRoot", ".flow/"],
                            }
                        ],
                    },
                }
            }
            transaction.write_internal_json(
                "full-policy.json",
                {"workspaceRoot": "/Users/private/project", "downloadRoot": "/Users/private/out"},
            )
            transaction.write_result_json(
                "beta-receipt.json", {"workspaceRoot": "/Users/private/project"}
            )

            with patch.object(main_release, "PROJECT_ROOT", root):
                bundle, bundle_hash = main_release._write_review_projection(
                    transaction,
                    config,
                    manifest,
                    channel="beta",
                    branch="public-beta/1.0.0-deadbeef",
                    commit="d" * 40,
                    tree="e" * 40,
                )

            self.assertEqual(hashlib.sha256(bundle.read_bytes()).hexdigest(), bundle_hash)
            with zipfile.ZipFile(bundle) as archive:
                names = set(archive.namelist())
                self.assertNotIn("beta-receipt.json", names)
                self.assertNotIn("full-policy.json", names)
                identity = json.loads(archive.read("review-identity.json"))
                self.assertEqual(
                    set(identity),
                    {
                        "schemaVersion",
                        "channel",
                        "releaseId",
                        "project",
                        "version",
                        "sourceCommit",
                        "sourceTree",
                        "candidateContentSha256",
                        "candidateArchiveSha256",
                        "branch",
                        "commit",
                        "tree",
                    },
                )
                exceptions = archive.read("public-exceptions.json").decode("utf-8")
                self.assertIn("/Users/", exceptions)
                self.assertIn("workspaceRoot", exceptions)
                self.assertIn(".flow/", exceptions)
                self.assertNotIn("/Users/private/project", archive.read("review-identity.json").decode("utf-8"))

    def test_beta_and_stable_review_channels_do_not_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            transaction = ReleaseTransaction(root / "tx", "1.0.0-deadbeef")
            beta = transaction.review_channel("beta")
            stable = transaction.review_channel("stable")
            beta.mkdir(parents=True)
            stable.mkdir(parents=True)
            (beta / "beta.json").write_text("{}\n", encoding="utf-8")
            (stable / "stable.json").write_text("{}\n", encoding="utf-8")

            self.assertNotEqual(beta, stable)
            self.assertTrue((beta / "beta.json").is_file())
            self.assertTrue((stable / "stable.json").is_file())
            with self.assertRaises(ReleaseTransactionError):
                transaction.review_channel("unknown")


if __name__ == "__main__":
    unittest.main()
