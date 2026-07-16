from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from script.project.main_boundary import MainBoundaryError, inspect_main_boundary
from script.project.main_content import load_main_content
from script.project import main_release

ROOT = Path(__file__).resolve().parents[1]


class MainBoundaryTest(unittest.TestCase):
    def test_declaration_is_categorized_and_public_boundary_closes(self):
        stable = load_main_content(ROOT)
        self.assertEqual(
            set(stable["categories"]),
            {"runtime", "automation", "packageTemplate", "documentation"},
        )
        self.assertIn("dist/data-pipeline/improvement/**", stable["generatedState"])
        self.assertNotIn("dist/data-pipeline/improvement/**", stable["include"])
        report = inspect_main_boundary(ROOT, stable)
        self.assertEqual(report["workflowDependencies"]["workflowCount"], 3)
        self.assertGreater(report["automationImports"]["moduleCount"], 0)
        self.assertGreater(report["declaredContent"]["selectedFileCount"], 0)

    def test_review_delta_is_categorized_for_ai(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            (root / "service").mkdir()
            (root / "service/app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "README.md").write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            (root / "service/app.py").write_text("VALUE = 2\n", encoding="utf-8")
            (root / "README.md").write_text("two\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "candidate"], cwd=root, check=True)
            candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            state = root / "state"
            state.mkdir()
            config = {
                "stable": {
                    "categories": {
                        "runtime": ["service/**"],
                        "documentation": ["README.md"],
                    }
                }
            }
            with patch.object(main_release, "PROJECT_ROOT", root):
                report = main_release._write_review_delta(
                    state, config, base_ref=base, candidate_commit=candidate
                )
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(payload["counts"]["runtime"], 1)
            self.assertEqual(payload["counts"]["documentation"], 1)
            self.assertEqual(payload["counts"]["uncategorized"], 0)

    def test_workflow_cannot_depend_on_dev_flow(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            (root / ".github/workflows").mkdir(parents=True)
            (root / ".github/workflows/bad.yml").write_text(
                "name: bad\non: workflow_dispatch\njobs:\n  bad:\n    steps:\n      - run: ./flow run\n",
                encoding="utf-8",
            )
            (root / "automation").mkdir()
            (root / "automation/__init__.py").write_text("", encoding="utf-8")
            stable = {
                "include": ["automation/**", ".github/workflows/**"],
                "internalOnly": ["script/**"],
                "forbidden": ["script/**"],
                "required": [".github/workflows/bad.yml"],
                "generated": [],
                "categories": {"automation": ["automation/**", ".github/workflows/**"]},
            }
            with self.assertRaises(MainBoundaryError):
                inspect_main_boundary(root, stable)


if __name__ == "__main__":
    unittest.main()
