from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from script.project.public_candidate_check import PublicCandidateError, inspect_candidate


CONFIG = {
    "project": {"id": "spider"},
    "stable": {
        "contentManifest": {"path": "PUBLIC-CONTENT-MANIFEST.json"},
        "internalOnly": ["script/**", ".flow/**", "AGENTS.md", "docs/internal/**"],
        "required": ["README.md", "PUBLIC-CONTENT-MANIFEST.json"],
    },
}


class PublicCandidateCheckTest(unittest.TestCase):
    def _candidate(self, root: Path, managed: list[str]) -> None:
        (root / "README.md").write_text("ok\n", encoding="utf-8")
        for value in managed:
            path = root / value
            if value == "PUBLIC-CONTENT-MANIFEST.json":
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x\n", encoding="utf-8")
        (root / "PUBLIC-CONTENT-MANIFEST.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "project": "spider",
                    "managedFiles": managed,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def test_accepts_exact_public_managed_set(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            self._candidate(root, ["README.md", "PUBLIC-CONTENT-MANIFEST.json"])
            result = inspect_candidate(root, CONFIG)
            self.assertEqual(
                result["managedFiles"],
                ["PUBLIC-CONTENT-MANIFEST.json", "README.md"],
            )

    def test_rejects_internal_path_in_manifest(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            self._candidate(
                root,
                ["README.md", "script/private.py", "PUBLIC-CONTENT-MANIFEST.json"],
            )
            with self.assertRaisesRegex(PublicCandidateError, "内部路径"):
                inspect_candidate(root, CONFIG)


if __name__ == "__main__":
    unittest.main()
