from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from script.project import quality_command as check_task
from script.project.environment import inspect_python, inspect_project_environment


class PythonEnvironmentContractTest(unittest.TestCase):
    def test_missing_venv_has_single_initialization_action(self):
        with tempfile.TemporaryDirectory() as td:
            status = inspect_project_environment(Path(td))
        self.assertFalse(status["ready"])
        self.assertIn("尚未初始化", status["error"])
        self.assertEqual(status["nextAction"], "python3 script/project/init_env.py")

    def test_staging_reuses_main_worktree_environment(self):
        staging = Path("/tmp/staging-project")
        common = Path("/tmp/main-project")
        ready = {"ready": True, "python": str(common / ".venv/bin/python")}
        with patch.dict(os.environ, {"FLOW_STAGING": "1"}), patch(
            "script.project.environment._common_repository_root", return_value=common
        ), patch("script.project.environment.inspect_python", return_value=ready) as inspect:
            status = inspect_project_environment(staging)
        inspect.assert_called_once_with(common / ".venv/bin/python")
        self.assertTrue(status["ready"])

    def test_dependency_mismatch_is_not_reported_as_code_failure(self):
        payload = {
            "version": [3, 12],
            "actual": {"lxml": "6.0.2", "mojimoji": "0.0.12", "requests": "2.32.5"},
            "expected": {"lxml": "6.0.2", "mojimoji": "0.0.13", "requests": "2.32.5"},
        }
        completed = type("Completed", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()
        with tempfile.TemporaryDirectory() as td:
            python = Path(td) / "python"
            python.write_text("stub", "utf-8")
            python.chmod(0o755)
            with patch("script.project.environment.subprocess.run", return_value=completed):
                status = inspect_python(python)
        self.assertFalse(status["ready"])
        self.assertIn("mojimoji", status["error"])
        self.assertIn("--recreate", status["nextAction"])

    def test_flow_check_stops_before_quality_when_environment_is_missing(self):
        missing = {
            "ready": False,
            "error": "项目 Python 虚拟环境尚未初始化",
            "nextAction": "python3 script/project/init_env.py",
        }
        with patch("script.project.quality_command.inspect_project_environment", return_value=missing), patch(
            "script.project.quality_command.run_logged"
        ) as run_logged:
            value = check_task.run(Path("."), ["--full"], {"quality": {"full": [["never"]]}}, None)
        run_logged.assert_not_called()
        self.assertEqual(value["exitCode"], 20)
        self.assertEqual(value["next"], "python3 script/project/init_env.py")


if __name__ == "__main__":
    unittest.main()
