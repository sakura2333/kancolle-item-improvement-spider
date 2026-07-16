from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from script.project.public_content_audit import PublicContentAuditError, inspect_public_text
from script.project.stable_command import _matches


ROOT = Path(__file__).resolve().parents[1]


class PublicContentAuditTest(unittest.TestCase):
    def test_rejects_internal_control_plane_reference(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            (root / "README.md").write_text("run ./flow update\n", encoding="utf-8")
            with self.assertRaises(PublicContentAuditError):
                inspect_public_text(root, {"publicForbiddenText": ["./flow"]})

    def test_rejects_missing_python_module_entrypoint(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            (root / "README.md").write_text("python -m service.missing_cli\n", encoding="utf-8")
            with self.assertRaisesRegex(PublicContentAuditError, "missing-module-entrypoint"):
                inspect_public_text(root, {"publicForbiddenText": []})

    def test_rejects_missing_public_markdown_path(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            (root / "README.md").write_text("See `docs/public/MISSING.md`.\n", encoding="utf-8")
            with self.assertRaisesRegex(PublicContentAuditError, "missing-public-path"):
                inspect_public_text(root, {"publicForbiddenText": []})

    def test_current_declared_public_files_do_not_expose_private_entrypoints(self):
        declaration = json.loads((ROOT / "release/public-content.json").read_text(encoding="utf-8"))
        patterns = [pattern for values in declaration["categories"].values() for pattern in values]
        internal = declaration["internalOnly"]
        with tempfile.TemporaryDirectory() as temp_name:
            candidate = Path(temp_name)
            for source in ROOT.rglob("*"):
                if not source.is_file() or ".git" in source.parts:
                    continue
                relative = source.relative_to(ROOT).as_posix()
                if not any(_matches(relative, pattern) for pattern in patterns):
                    continue
                if any(_matches(relative, pattern) for pattern in internal):
                    continue
                if relative in declaration["generated"]:
                    continue
                target = candidate / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            (candidate / "RELEASE-NOTES.md").write_text("# Release\n", encoding="utf-8")
            (candidate / "PUBLIC-CONTENT-MANIFEST.json").write_text(
                json.dumps({"schemaVersion": 2, "project": declaration["projectId"], "managedFiles": []}) + "\n",
                encoding="utf-8",
            )
            result = inspect_public_text(candidate, declaration)
            self.assertEqual(result["findingCount"], 0)
            self.assertGreater(result["moduleReferenceCount"], 0)


if __name__ == "__main__":
    unittest.main()
