from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from script.project.ownership import (
    classify_path,
    git_dirty_paths,
    project_owned_identity,
    split_paths,
    update_policy,
)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class ProjectOwnershipTest(unittest.TestCase):
    def make_repo(self, base: Path) -> Path:
        root = base / "repo"
        root.mkdir()
        (root / "configs").mkdir()
        (root / "configs/generated-state.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "id": "online-data",
                    "role": "generated-state",
                    "backend": "git-ref",
                    "ref": "online",
                    "management": "project-managed",
                    "manifestPath": ".generated-state/manifest.json",
                    "exportPaths": ["data/output", "package/manifest.json"],
                    "baselineSyncPaths": ["data/output"],
                    "forbiddenPaths": ["service"],
                    "excludePatterns": [],
                }
            ),
            encoding="utf-8",
        )
        (root / "service").mkdir()
        (root / "service/app.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "data/output").mkdir(parents=True)
        (root / "data/output/value.json").write_text("{\"value\":1}\n", encoding="utf-8")
        (root / "package").mkdir()
        (root / "package/manifest.json").write_text("{}\n", encoding="utf-8")
        git(root, "init", "-q", "-b", "dev")
        git(root, "config", "user.name", "test")
        git(root, "config", "user.email", "test@example.invalid")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "base")
        return root

    def test_generated_changes_do_not_change_code_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.make_repo(Path(temp))
            before = project_owned_identity(root)
            (root / "data/output/value.json").write_text("{\"value\":2}\n", encoding="utf-8")
            (root / "package/manifest.json").write_text("{\"version\":2}\n", encoding="utf-8")
            self.assertEqual(project_owned_identity(root), before)

    def test_project_code_change_changes_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.make_repo(Path(temp))
            before = project_owned_identity(root)
            (root / "service/app.py").write_text("VALUE = 2\n", encoding="utf-8")
            self.assertNotEqual(project_owned_identity(root), before)

    def test_rename_reports_both_old_and_new_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.make_repo(Path(temp))
            git(root, "mv", "service/app.py", "service/main.py")
            self.assertEqual(
                git_dirty_paths(root),
                ["service/app.py", "service/main.py"],
            )

    def test_classification_and_update_protection_share_one_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.make_repo(Path(temp))
            self.assertEqual(classify_path(root, "service/app.py"), "project-owned")
            self.assertEqual(classify_path(root, "data/output/value.json"), "generated-state")
            self.assertEqual(classify_path(root, "package/manifest.json"), "generated-state")
            self.assertEqual(classify_path(root, ".flow/state/checks/full.json"), "local-preserved")
            values = split_paths(
                root,
                ["service/app.py", "data/output/value.json", ".flow/state/x.json"],
            )
            self.assertEqual(values["project-owned"], ["service/app.py"])
            policy = update_policy(root)
            self.assertIn("data/output/**", policy["protected"])
            self.assertIn("package/manifest.json/**", policy["protected"])
            self.assertEqual(policy["identityProvider"], "script.project.ownership:identity_value")
            self.assertEqual(
                policy["candidateVerifier"],
                ["{project-python}", "script/project/cli.py", "verify-candidate", "--json"],
            )
            self.assertNotIn("postSwitchCommand", policy)


if __name__ == "__main__":
    unittest.main()
