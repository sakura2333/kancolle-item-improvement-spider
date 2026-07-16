from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from script.project import flow_baseline


def _run_git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, text=True, capture_output=True)


def _init_project(base: Path) -> Path:
    root = base / "project"
    root.mkdir()
    (root / "VERSION").write_text("1.0.24\n", encoding="utf-8")
    (root / "mise.toml").write_text("[tools]\npython=\"3.14.6\"\nuv=\"0.11.28\"\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname=\"test\"\nversion=\"0.0.0\"\nrequires-python=\">=3.14,<3.15\"\ndependencies=[]\n", encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\nrevision = 3\nrequires-python = \"==3.14.*\"\n", encoding="utf-8")
    (root / "configs").mkdir()
    (root / "configs/generated-state.json").write_text(
        json.dumps({
            "schemaVersion": 1,
            "id": "test-generated",
            "role": "generated-state",
            "backend": "git-ref",
            "ref": "online",
            "management": "project-managed",
            "manifestPath": ".generated-state/manifest.json",
            "exportPaths": ["dist/out"],
            "baselineSyncPaths": ["dist/out"],
            "forbiddenPaths": ["script", "tests", "configs", "VERSION"],
            "excludePatterns": [],
        }),
        encoding="utf-8",
    )
    (root / "app.py").write_text("print('ok')\n", encoding="utf-8")
    _run_git(root, "init", "-b", "dev")
    _run_git(root, "config", "user.name", "Test")
    _run_git(root, "config", "user.email", "test@example.invalid")
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "baseline")
    return root


class FlowBaselineTest(unittest.TestCase):
    def test_baseline_file_is_excluded_from_content_hash(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = _init_project(Path(temp_name))
            before = flow_baseline.content_hash(root)
            flow_baseline.write_current_state(root, source="test")
            after = flow_baseline.content_hash(root)
            self.assertEqual(after, before)
            state = flow_baseline.read_state(root)
            self.assertIsNotNone(state)
            self.assertEqual(state["contentIdentity"]["scheme"], "flow-content-sha256")
            self.assertEqual(state["contentIdentity"]["value"], before)
            self.assertTrue(any(item["path"] == "uv.lock" for item in state["dependencyFiles"]))

    def test_receipt_must_bind_content_and_lock_hash(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = _init_project(Path(temp_name))
            receipt_dir = root / ".flow/state/checks"
            receipt_dir.mkdir(parents=True)
            receipt = {
                "schemaVersion": 2,
                "profile": "before",
                "contentHash": f"sha256:{flow_baseline.content_hash(root)}",
                "lockHash": f"sha256:{flow_baseline.lock_hash(root)}",
            }
            (receipt_dir / "before.json").write_text(json.dumps(receipt), encoding="utf-8")
            _, loaded, _ = flow_baseline.latest_quick_receipt(root)
            self.assertTrue(flow_baseline.receipt_binds_current_content(root, loaded))
            (root / "app.py").write_text("print('changed')\n", encoding="utf-8")
            self.assertFalse(flow_baseline.receipt_binds_current_content(root, loaded))


if __name__ == "__main__":
    unittest.main()
