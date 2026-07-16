from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from script.project._common import ProjectCommandError
from script.project.directory_governance import (
    remove_deprecated_local_dirs,
    verify_directory_governance,
)


class DirectoryGovernanceTest(unittest.TestCase):
    def test_path_module_import_has_no_directory_side_effects(self):
        path_module = Path(__file__).resolve().parents[1] / "configs" / "path.py"
        with tempfile.TemporaryDirectory() as temp_name:
            fake_root = Path(temp_name) / "project"
            fake_configs = fake_root / "configs"
            fake_configs.mkdir(parents=True)
            copied = fake_configs / "path.py"
            copied.write_bytes(path_module.read_bytes())

            spec = importlib.util.spec_from_file_location("isolated_project_paths", copied)
            self.assertIsNotNone(spec)
            module = importlib.util.module_from_spec(spec)
            self.assertIsNotNone(spec.loader)
            spec.loader.exec_module(module)

            self.assertFalse((fake_root / "data").exists())
            self.assertFalse((fake_root / "log").exists())
            self.assertFalse((fake_root / ".flow/packages").exists())
            self.assertFalse((fake_root / "dist").exists())

    def test_cleanup_removes_only_retired_local_roots(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            for relative in ("data", "log", ".flow/packages", "service/generated_state"):
                target = root / relative
                target.mkdir(parents=True)
                (target / "legacy.txt").write_text("legacy\n", encoding="utf-8")
            protected = root / ".flow/local/source-cache"
            protected.mkdir(parents=True)
            (protected / "keep.txt").write_text("keep\n", encoding="utf-8")
            generated = root / "dist/data-pipeline"
            generated.mkdir(parents=True)

            removed = remove_deprecated_local_dirs(root)

            self.assertEqual(removed, ["data", "log", ".flow/packages", "service/generated_state"])
            self.assertTrue((protected / "keep.txt").is_file())
            self.assertTrue(generated.is_dir())

    def test_cleanup_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            outside = root / "outside"
            outside.mkdir()
            try:
                (root / "data").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")
            with self.assertRaisesRegex(ProjectCommandError, "符号链接"):
                remove_deprecated_local_dirs(root)
            self.assertTrue(outside.is_dir())

    def test_verify_rejects_retired_roots(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            retired = root / "configs/templates"
            retired.mkdir(parents=True)
            (retired / "legacy.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ProjectCommandError, "configs/templates"):
                verify_directory_governance(root)


    def test_verify_allows_transient_empty_retired_project_directory(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            (root / "configs/templates").mkdir(parents=True)
            verify_directory_governance(root)


    def test_verify_allows_cache_only_moved_code_directory(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            cache = root / "service/generated_state/__pycache__"
            cache.mkdir(parents=True)
            (cache / "legacy.cpython-314.pyc").write_bytes(b"cache")
            verify_directory_governance(root)

    def test_verify_rejects_source_in_moved_code_directory(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            retired = root / "service/generated_state"
            retired.mkdir(parents=True)
            (retired / "legacy.py").write_text("VALUE = 1\n", encoding="utf-8")
            with self.assertRaisesRegex(ProjectCommandError, "service/generated_state"):
                verify_directory_governance(root)

    def test_current_project_has_no_retired_roots(self):
        root = Path(__file__).resolve().parents[1]
        # Candidate/worktree tests may leave Python cache directories only under
        # normal packages; the retired top-level roots themselves must be gone.
        verify_directory_governance(root)


if __name__ == "__main__":
    unittest.main()
