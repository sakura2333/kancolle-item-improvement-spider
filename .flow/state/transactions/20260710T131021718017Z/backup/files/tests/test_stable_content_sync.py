from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from script.project import stable_command as stable

ROOT = Path(__file__).resolve().parents[1]
from script.project.runtime import load
CONFIG = load()
LEGACY_TREE = "4065dfa2cc3732c2c2ca70d60ec889dc24d738fe"
MIGRATION_ID = CONFIG["stable"]["contentManifest"]["migrationId"]


class StableContentSyncTest(unittest.TestCase):
    def _git_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)

    def test_candidate_writes_public_content_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp)
            (candidate / "README.md").write_text("hello\n", encoding="utf-8")
            value = stable._write_public_content_manifest(candidate, CONFIG, "a" * 40, "1.0.4-rc.2")
            path = candidate / "STABLE-CONTENT-MANIFEST.json"
            self.assertTrue(path.is_file())
            self.assertEqual(value["migrationId"], MIGRATION_ID)
            self.assertEqual(value["managedFiles"], ["README.md", "STABLE-CONTENT-MANIFEST.json"])

    def test_one_time_cleanup_removes_all_legacy_tree_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp) / "worktree"
            candidate = Path(tmp) / "candidate"
            worktree.mkdir()
            candidate.mkdir()
            (worktree / "legacy.txt").write_text("legacy\n", encoding="utf-8")
            (worktree / "legacy-dir").mkdir()
            (worktree / "legacy-dir" / "old.txt").write_text("old\n", encoding="utf-8")
            self._git_repo(worktree)
            (candidate / "README.md").write_text("new\n", encoding="utf-8")
            stable._synchronize_candidate(worktree, candidate, "one-time-full-cleanup", set())
            self.assertFalse((worktree / "legacy.txt").exists())
            self.assertFalse((worktree / "legacy-dir").exists())
            self.assertTrue((worktree / "README.md").is_file())
            self.assertTrue((worktree / ".git").is_dir())

    def test_incremental_sync_only_removes_previously_managed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp) / "worktree"
            candidate = Path(tmp) / "candidate"
            worktree.mkdir()
            candidate.mkdir()
            (worktree / "managed-old.txt").write_text("old\n", encoding="utf-8")
            (worktree / "unknown-owner.txt").write_text("keep\n", encoding="utf-8")
            (candidate / "managed-new.txt").write_text("new\n", encoding="utf-8")
            stable._synchronize_candidate(
                worktree,
                candidate,
                "managed-incremental",
                {"managed-old.txt", "managed-new.txt"},
            )
            self.assertFalse((worktree / "managed-old.txt").exists())
            self.assertTrue((worktree / "managed-new.txt").is_file())
            self.assertTrue((worktree / "unknown-owner.txt").is_file())

    def test_full_cleanup_is_authorized_only_for_exact_legacy_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            mode, managed = stable._release_mode(worktree, CONFIG, LEGACY_TREE)
            self.assertEqual(mode, "one-time-full-cleanup")
            self.assertEqual(managed, set())
            with self.assertRaises(stable.StableReleaseError):
                stable._release_mode(worktree, CONFIG, "b" * 40)

    def test_manifest_switches_future_releases_to_incremental(self):
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            path = worktree / "STABLE-CONTENT-MANIFEST.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "project": CONFIG["project"]["id"],
                        "migrationId": MIGRATION_ID,
                        "managedFiles": ["README.md", "STABLE-CONTENT-MANIFEST.json"],
                    }
                ),
                encoding="utf-8",
            )
            mode, managed = stable._release_mode(worktree, CONFIG, "c" * 40)
            self.assertEqual(mode, "managed-incremental")
            self.assertIn("README.md", managed)


if __name__ == "__main__":
    unittest.main()
