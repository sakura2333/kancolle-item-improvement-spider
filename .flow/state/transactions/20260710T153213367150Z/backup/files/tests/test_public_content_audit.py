from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from script.project.public_content_audit import PublicContentAuditError, inspect_public_text
from script.project import stable_command


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
        from script.project.public_content import load_public_content
        declaration = load_public_content(ROOT)
        with tempfile.TemporaryDirectory() as temp_name:
            candidate = Path(temp_name)
            selected = stable_command._public_paths(ROOT, {"stable": declaration})
            for relative in selected:
                if relative in declaration["generated"]:
                    continue
                source = ROOT / relative
                target = candidate / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            (candidate / "RELEASE-NOTES.md").write_text("# Release\n", encoding="utf-8")
            (candidate / ".gitignore").write_text("\n".join(declaration["publicGitignore"]) + "\n", encoding="utf-8")
            (candidate / "PUBLIC-CONTENT-MANIFEST.json").write_text(
                json.dumps({"schemaVersion": 2, "project": declaration["projectId"], "managedFiles": []}) + "\n",
                encoding="utf-8",
            )
            result = inspect_public_text(candidate, declaration)
            self.assertEqual(result["findingCount"], 0)
            self.assertGreater(result["moduleReferenceCount"], 0)

    def test_public_paths_ignore_matching_untracked_local_config(self):
        import subprocess

        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            (root / "configs").mkdir()
            (root / "configs/default.json").write_text('{"public":true}\n', encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "add", "configs/default.json"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            (root / "configs/wikiwiki-crawler.local.json").write_text(
                '{"browserProfileDir":".flow/local/profile"}\n', encoding="utf-8"
            )

            selected = stable_command._public_paths(
                root,
                {
                    "stable": {
                        "include": ["configs/**"],
                        "internalOnly": [],
                        "required": ["configs/default.json"],
                        "generated": [],
                    }
                },
            )

            self.assertEqual(selected, ["configs/default.json"])

    def test_review_token_requires_exact_registered_exception(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            (root / "README.md").write_text("NPM_TOKEN\n", encoding="utf-8")
            stable = {
                "publicForbiddenText": [],
                "publicReviewText": ["NPM_TOKEN"],
                "publicExceptions": {"exceptions": []},
            }
            with self.assertRaisesRegex(PublicContentAuditError, "unregistered-public-exception"):
                inspect_public_text(root, stable)

    def test_exception_occurrence_count_is_exact(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            (root / "README.md").write_text("NPM_TOKEN NPM_TOKEN\n", encoding="utf-8")
            stable = {
                "publicForbiddenText": [],
                "publicReviewText": ["NPM_TOKEN"],
                "publicExceptions": {
                    "exceptions": [
                        {
                            "id": "npm-token",
                            "category": "public-contract",
                            "owner": "release",
                            "review": "mechanical-and-ai",
                            "expires": None,
                            "matches": [
                                {"path": "README.md", "literal": "NPM_TOKEN", "expectedOccurrences": 1}
                            ],
                            "forbiddenContent": [],
                        }
                    ]
                },
            }
            with self.assertRaisesRegex(PublicContentAuditError, "public-exception-count-mismatch"):
                inspect_public_text(root, stable)


if __name__ == "__main__":
    unittest.main()
