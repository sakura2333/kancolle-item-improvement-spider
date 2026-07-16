from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from script.flow import recovery as module


class RecoveryPackageTest(unittest.TestCase):
    def test_package_contains_tracked_files_bundle_manifest_handoff_and_sidecar(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            output = base / "out"
            project.mkdir()
            output.mkdir()
            (project / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            (project / "README.md").write_text("hello\n", encoding="utf-8")
            (project / ".flow").mkdir()
            (project / ".flow/local.json").write_text("{}\n", encoding="utf-8")
            subprocess.run(["git", "init", "-b", "dev"], cwd=project, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=project, check=True)
            subprocess.run(["git", "add", "VERSION", "README.md"], cwd=project, check=True)
            subprocess.run(["git", "commit", "-m", "baseline"], cwd=project, check=True, capture_output=True)
            config = {
                "project": {"id": "demo", "versionFile": "VERSION"},
                "capabilities": {"flow.command": True, "update.transaction": True, "recovery.package": True},
                "recovery": {
                    "includeLocal": [".flow/local.json"],
                    "exclude": [".flow/state", ".venv"],
                },
            }
            explicit = output / "exact-recovery.zip"
            result = module.execute(project, "create", ["--output", str(explicit)], config)
            self.assertEqual(result["status"], "成功")
            package = explicit
            self.assertTrue(package.is_file())
            sidecar = Path(str(package) + ".flow.json")
            self.assertTrue(sidecar.is_file())
            identity = json.loads(sidecar.read_text("utf-8"))
            self.assertEqual(identity["packageType"], "recovery")
            self.assertEqual(identity["projectId"], "demo")
            manifest = module._verify_zip(package)
            paths = {item["path"] for item in manifest["files"]}
            self.assertIn("project/README.md", paths)
            self.assertIn("private/.flow/local.json", paths)
            self.assertIn("git/project.bundle", paths)
            self.assertIn("GPT-HANDOFF.md", paths)

            extract = base / "extract"
            with zipfile.ZipFile(package) as archive:
                archive.extract("git/project.bundle", extract)
                archive.extract("private/.flow/local.json", extract)
            restored = base / "restored"
            subprocess.run(
                ["git", "clone", str(extract / "git/project.bundle"), str(restored)],
                check=True,
                capture_output=True,
            )
            original_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip()
            restored_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=restored, text=True).strip()
            self.assertEqual(restored_commit, original_commit)
            self.assertEqual((restored / "README.md").read_text("utf-8"), "hello\n")
            self.assertEqual((extract / "private/.flow/local.json").read_text("utf-8"), "{}\n")

    def test_generated_state_is_private_and_untracked_generated_files_are_included(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            project.mkdir()
            (project / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            (project / "README.md").write_text("code\n", encoding="utf-8")
            generated = project / "dist/data-pipeline/sources/example/tracked.nedb"
            generated.parent.mkdir(parents=True)
            generated.write_text("tracked-generated\n", encoding="utf-8")
            untracked = project / "dist/data-pipeline/sources/example/runtime.nedb"
            subprocess.run(["git", "init", "-b", "dev"], cwd=project, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=project, check=True)
            subprocess.run(["git", "add", "VERSION", "README.md", str(generated.relative_to(project))], cwd=project, check=True)
            subprocess.run(["git", "commit", "-m", "baseline"], cwd=project, check=True, capture_output=True)
            untracked.write_text("runtime-generated\n", encoding="utf-8")
            untracked_code = project / "service/new_feature.py"
            untracked_code.parent.mkdir(parents=True)
            untracked_code.write_text("VALUE = 1\n", encoding="utf-8")
            config = {
                "project": {"id": "demo", "versionFile": "VERSION"},
                "capabilities": {"flow.command": True, "update.transaction": True, "recovery.package": True},
                "recovery": {
                    "includeLocal": [],
                    "includeGeneratedState": ["dist/data-pipeline/sources"],
                    "exclude": [".venv"],
                },
            }
            files = module._collect(project, config)
            self.assertIn("project/README.md", files)
            self.assertIn("project/service/new_feature.py", files)
            self.assertNotIn("project/dist/data-pipeline/sources/example/tracked.nedb", files)
            self.assertIn(
                "private/generated-state/dist/data-pipeline/sources/example/tracked.nedb", files
            )
            self.assertIn(
                "private/generated-state/dist/data-pipeline/sources/example/runtime.nedb", files
            )


if __name__ == "__main__":
    unittest.main()
