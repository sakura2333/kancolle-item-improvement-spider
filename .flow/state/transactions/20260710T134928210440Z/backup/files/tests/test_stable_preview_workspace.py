from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from script.project import stable_command


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class StablePreviewWorkspaceTest(unittest.TestCase):
    def make_repo(self, base: Path) -> Path:
        root = base / "repo"
        root.mkdir()
        (root / "configs").mkdir()
        (root / "configs/generated-state.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "id": "test-state",
                    "role": "generated-state",
                    "backend": "git-ref",
                    "ref": "online",
                    "management": "project-managed",
                    "manifestPath": ".generated-state/manifest.json",
                    "exportPaths": ["data/output"],
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
        (root / "data/output/value.json").write_text('{"value":1}\n', encoding="utf-8")
        git(root, "init", "-q", "-b", "dev")
        git(root, "config", "user.name", "test")
        git(root, "config", "user.email", "test@example.invalid")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "base")
        return root

    def test_generated_and_local_changes_are_allowed_but_not_public_bound(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = self.make_repo(Path(temp_name))
            before = stable_command._workspace_source_state(root)
            (root / "data/output/value.json").write_text('{"value":2}\n', encoding="utf-8")
            (root / "data/output/new.json").write_text('{"new":true}\n', encoding="utf-8")
            (root / ".flow/local/source-cache").mkdir(parents=True)
            (root / ".flow/local/source-cache/cache.html").write_text("local\n", encoding="utf-8")

            after = stable_command._workspace_source_state(root)

            self.assertEqual(before["generatedDirtyCount"], 0)
            self.assertEqual(after["generatedDirtyCount"], 2)
            self.assertNotIn("generatedStateSha256", after)
            self.assertEqual(after["localPreservedDirtyCount"], 1)
            selected = stable_command._public_paths(
                root,
                {
                    "stable": {
                        "include": ["service/**"],
                        "internalOnly": [".flow/local/source-cache/**"],
                        "required": ["service/app.py"],
                        "generated": [],
                    }
                },
            )
            self.assertNotIn("data/output/new.json", selected)
            self.assertNotIn(".flow/local/source-cache/cache.html", selected)

    def test_project_owned_change_blocks_preview_source(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = self.make_repo(Path(temp_name))
            (root / "service/app.py").write_text("VALUE = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(
                stable_command.StableReleaseError,
                "project-owned",
            ):
                stable_command._workspace_source_state(root)

    def test_load_latest_ignores_generated_state_drift(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = self.make_repo(Path(temp_name))
            config = {
                "stable": {
                    "previewRoot": ".flow/state/public-candidates",
                    "include": ["service/**"],
                    "internalOnly": [],
                    "required": ["service/app.py"],
                    "generated": [],
                }
            }
            source_state = stable_command._workspace_source_state(root)
            release_id = "test-release"
            state_root = root / ".flow/state/public-candidates" / release_id
            candidate = state_root / "candidate"
            candidate.mkdir(parents=True)
            (candidate / "service").mkdir()
            (candidate / "service/app.py").write_text("VALUE = 1\n", encoding="utf-8")
            records = stable_command._candidate_records(candidate)
            manifest = {
                "schemaVersion": 6,
                "releaseId": release_id,
                "sourceCommit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=root, text=True
                ).strip(),
                "sourceTree": subprocess.check_output(
                    ["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True
                ).strip(),
                "stableConfigSha256": stable_command._config_hash(config),
                "sourceState": source_state,
                "candidateSha256": stable_command._candidate_hash(records),
            }
            (state_root / "candidate-manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (root / ".flow/state/public-candidates/latest.json").write_text(
                json.dumps({"releaseId": release_id}), encoding="utf-8"
            )
            (root / "data/output/value.json").write_text('{"value":3}\n', encoding="utf-8")

            state_root_loaded, loaded = stable_command._load_latest(root, config)
            self.assertEqual(state_root_loaded, state_root)
            self.assertEqual(loaded["releaseId"], release_id)


if __name__ == "__main__":
    unittest.main()
