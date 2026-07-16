from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from script.project import quality_command as check_task
from script.project.environment import NEXT_ACTION, inspect_project_environment


class PythonEnvironmentContractTest(unittest.TestCase):
    def _project(self, base: Path) -> Path:
        root = base / "project"
        root.mkdir()
        (root / "mise.toml").write_text(
            'min_version = "2026.7.0"\n[tools]\npython = "3.14.6"\nuv = "0.11.28"\n',
            encoding="utf-8",
        )
        (root / "pyproject.toml").write_text(
            "[project]\nname='test'\nversion='0.0.0'\nrequires-python='>=3.14,<3.15'\ndependencies=[]\n"
            "[tool.uv]\npackage=false\npython-downloads='never'\n",
            encoding="utf-8",
        )
        (root / "uv.lock").write_text(
            "version = 1\nrevision = 3\nrequires-python = '==3.14.*'\n",
            encoding="utf-8",
        )
        return root

    def test_missing_mise_has_single_install_action(self):
        with tempfile.TemporaryDirectory() as td, patch("script.project.environment.shutil.which", return_value=None):
            status = inspect_project_environment(Path(td))
        self.assertFalse(status["ready"])
        self.assertIn("未找到 mise", status["error"])
        self.assertEqual(status["nextAction"], NEXT_ACTION)

    def test_missing_project_contract_is_reported_before_execution(self):
        with tempfile.TemporaryDirectory() as td, patch("script.project.environment.shutil.which", return_value="/usr/bin/mise"):
            status = inspect_project_environment(Path(td))
        self.assertFalse(status["ready"])
        self.assertIn("mise.toml", status["error"])

    def test_mise_python_314_and_locked_uv_environment_is_ready(self):
        payload = {
            "version": [3, 14],
            "actual": {"jaconv": "0.5.0", "lxml": "6.0.2", "playwright": "1.61.0", "requests": "2.32.5"},
            "expected": {"jaconv": "0.5.0", "lxml": "6.0.2", "playwright": "1.61.0", "requests": "2.32.5"},
        }
        python = type("Completed", (), {"returncode": 0, "stdout": "3.14\n", "stderr": ""})()
        uv_version = type("Completed", (), {"returncode": 0, "stdout": "uv 0.11.28\n", "stderr": ""})()
        lock = type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        probe = type("Completed", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()
        with tempfile.TemporaryDirectory() as td:
            root = self._project(Path(td))
            with patch("script.project.environment.shutil.which", return_value="/usr/bin/mise"), patch(
                "script.project.environment.subprocess.run", side_effect=[python, uv_version, lock, probe]
            ) as run:
                status = inspect_project_environment(root)
        self.assertTrue(status["ready"])
        self.assertEqual(status["version"], [3, 14])
        self.assertEqual(status["uv"], "0.11.28")
        for call in run.call_args_list:
            self.assertEqual(call.args[0][:3], ["/usr/bin/mise", "exec", "--"])

    def test_uv_version_mismatch_is_rejected(self):
        python = type("Completed", (), {"returncode": 0, "stdout": "3.14\n", "stderr": ""})()
        uv_version = type("Completed", (), {"returncode": 0, "stdout": "uv 0.11.27\n", "stderr": ""})()
        with tempfile.TemporaryDirectory() as td:
            root = self._project(Path(td))
            with patch("script.project.environment.shutil.which", return_value="/usr/bin/mise"), patch(
                "script.project.environment.subprocess.run", side_effect=[python, uv_version]
            ):
                status = inspect_project_environment(root)
        self.assertFalse(status["ready"])
        self.assertIn("0.11.28", status["error"])

    def test_dependency_mismatch_is_not_reported_as_code_failure(self):
        payload = {
            "version": [3, 14],
            "actual": {"jaconv": "0.4.0", "lxml": "6.0.2", "playwright": "1.61.0", "requests": "2.32.5"},
            "expected": {"jaconv": "0.5.0", "lxml": "6.0.2", "playwright": "1.61.0", "requests": "2.32.5"},
        }
        calls = [
            type("Completed", (), {"returncode": 0, "stdout": "3.14\n", "stderr": ""})(),
            type("Completed", (), {"returncode": 0, "stdout": "uv 0.11.28\n", "stderr": ""})(),
            type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
            type("Completed", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})(),
        ]
        with tempfile.TemporaryDirectory() as td:
            root = self._project(Path(td))
            with patch("script.project.environment.shutil.which", return_value="/usr/bin/mise"), patch(
                "script.project.environment.subprocess.run", side_effect=calls
            ):
                status = inspect_project_environment(root)
        self.assertFalse(status["ready"])
        self.assertIn("jaconv", status["error"])
        self.assertEqual(status["nextAction"], NEXT_ACTION)

    def test_flow_check_stops_before_quality_when_environment_is_missing(self):
        missing = {"ready": False, "error": "项目 mise/uv 环境不可用", "nextAction": NEXT_ACTION}
        with patch("script.project.quality_command.inspect_project_environment", return_value=missing), patch(
            "script.project.quality_command.run_logged"
        ) as run_logged:
            value = check_task.run(Path("."), ["--full"], {"quality": {"full": [["never"]]}}, None)
        run_logged.assert_not_called()
        self.assertEqual(value["exitCode"], 20)
        self.assertEqual(value["next"], NEXT_ACTION)


if __name__ == "__main__":
    unittest.main()
