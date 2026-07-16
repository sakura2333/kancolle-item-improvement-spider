from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from script.project import main_release


def run(cwd: Path, *args: str) -> str:
    return subprocess.check_output(list(args), cwd=cwd, text=True).strip()


class MainBetaReleaseTest(unittest.TestCase):
    def test_prepare_beta_pushes_exact_shared_public_snapshot_and_does_not_touch_main(self):
        with tempfile.TemporaryDirectory() as temp_name:
            temp = Path(temp_name)
            remote = temp / "remote.git"
            repo = temp / "repo"
            subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            (repo / "old.txt").write_text("old\n", encoding="utf-8")
            (repo / "STABLE-CONTENT-MANIFEST.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "project": "demo",
                        "migrationId": "old-migration",
                        "managedFiles": ["old.txt", "STABLE-CONTENT-MANIFEST.json"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "legacy main"], cwd=repo, check=True)
            subprocess.run(["git", "remote", "add", "main-origin", str(remote)], cwd=repo, check=True)
            subprocess.run(["git", "push", "-q", "main-origin", "main"], cwd=repo, check=True)
            main_before = run(repo, "git", "rev-parse", "main-origin/main")
            subprocess.run(["git", "switch", "-q", "-c", "dev"], cwd=repo, check=True)

            state_root = repo / ".flow/state/public-candidates/1.0.24-deadbeef0000"
            candidate = state_root / "candidate"
            (candidate / "service").mkdir(parents=True)
            (candidate / "service/app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (candidate / "README.md").write_text("beta\n", encoding="utf-8")
            (candidate / "PUBLIC-CONTENT-MANIFEST.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 2,
                        "project": "demo",
                        "managedFiles": [
                            "PUBLIC-CONTENT-MANIFEST.json",
                            "README.md",
                            "service/app.py",
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            records = []
            for path in sorted(candidate.rglob("*")):
                if path.is_file():
                    records.append(
                        {
                            "path": path.relative_to(candidate).as_posix(),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "sizeBytes": path.stat().st_size,
                        }
                    )
            manifest = {
                "schemaVersion": 6,
                "releaseId": "1.0.24-deadbeef0000",
                "project": "demo",
                "version": "1.0.24",
                "sourceCommit": run(repo, "git", "rev-parse", "HEAD"),
                "sourceTree": run(repo, "git", "rev-parse", "HEAD^{tree}"),
                "candidateSha256": main_release.stable_command._candidate_hash(records),
                "files": records,
                "stage": "mechanical-preview",
            }
            state_root.mkdir(parents=True, exist_ok=True)
            (state_root / "candidate-manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            config = {
                "project": {"id": "demo", "versionFile": "VERSION"},
                "git": {
                    "development": {"remote": "origin", "branch": "dev"},
                    "stable": {"remote": "main-origin", "branch": "main"},
                },
                "stable": {
                    "previewRoot": ".flow/state/public-candidates",
                    "betaCandidateBranchPrefix": "public-beta/",
                    "categories": {
                        "runtime": ["service/**"],
                        "documentation": ["README.md", "PUBLIC-CONTENT-MANIFEST.json"],
                    },
                    "publicForbiddenText": ["./flow", "script/project", ".flow/state"],
                },
            }
            with (
                patch.object(main_release, "PROJECT_ROOT", repo),
                patch.object(main_release, "load_runtime", return_value=config),
                patch.object(main_release, "_verify_dev_pushed", return_value=manifest["sourceCommit"]),
                patch.object(main_release, "_stable_remote", return_value=("main-origin", str(remote))),
                patch.object(main_release.stable_command, "_load_latest", return_value=(state_root, manifest)),
            ):
                (repo / ".flow/state/public-candidates/latest.json").parent.mkdir(parents=True, exist_ok=True)
                (repo / ".flow/state/public-candidates/latest.json").write_text(
                    json.dumps({"releaseId": manifest["releaseId"]}), encoding="utf-8"
                )
                result = main_release.prepare_beta(confirm=True)

            self.assertEqual(result["status"], "prepared")
            self.assertEqual(result["channel"], "beta")
            self.assertEqual(result["branch"], "public-beta/1.0.24-deadbeef0000")
            beta_commit = run(
                repo,
                "git",
                "ls-remote",
                str(remote),
                "refs/heads/public-beta/1.0.24-deadbeef0000",
            ).split()[0]
            beta_files = run(repo, "git", "ls-tree", "-r", "--name-only", beta_commit).splitlines()
            self.assertEqual(
                beta_files,
                ["PUBLIC-CONTENT-MANIFEST.json", "README.md", "service/app.py"],
            )
            self.assertEqual(run(repo, "git", "rev-parse", "main-origin/main"), main_before)
            receipt = json.loads((state_root / "beta-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["schemaVersion"], 3)
            self.assertEqual(receipt["candidateSha256"], manifest["candidateSha256"])
            self.assertEqual(receipt["candidateContentSha256"], manifest["candidateSha256"])
            self.assertTrue(receipt["candidateArchiveSha256"])
            self.assertEqual(receipt["candidateArchive"], "candidate.zip")
            self.assertEqual(receipt["policy"], "shared-whitelist-public-snapshot")
            self.assertEqual(receipt["publicTextAudit"]["findingCount"], 0)
            self.assertFalse(receipt["formalVersionChanged"])
            self.assertFalse(receipt["mainChanged"])
            self.assertFalse(receipt["npmPublished"])
            self.assertFalse(receipt["onlinePublished"])
            bundle = repo / result["reviewBundle"]
            self.assertTrue(bundle.is_file())
            self.assertEqual(hashlib.sha256(bundle.read_bytes()).hexdigest(), result["reviewBundleSha256"])
            self.assertNotIn(str(repo), (state_root / "beta-receipt.json").read_text(encoding="utf-8"))
            inventory = json.loads((state_root / "beta-review-inventory.json").read_text(encoding="utf-8"))
            self.assertIsInstance(inventory["publicIsolation"], dict)
            with zipfile.ZipFile(bundle) as archive:
                self.assertEqual(
                    sorted(archive.namelist()),
                    [
                        "beta-receipt.json",
                        "beta-review-inventory.json",
                        "candidate-manifest.json",
                        "candidate.zip",
                        "public-content-audit.json",
                    ],
                )
                candidate_archive = archive.read("candidate.zip")
                self.assertEqual(
                    hashlib.sha256(candidate_archive).hexdigest(),
                    receipt["candidateArchiveSha256"],
                )
                for name in archive.namelist():
                    if not name.endswith(".json"):
                        continue
                    self.assertNotIn(str(repo), archive.read(name).decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
