from __future__ import annotations

import fnmatch
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from script.project import quality_command, stable_command
from script.project.runtime import load


class QualityProfileBoundaryTest(unittest.TestCase):
    def test_release_policy_file_is_not_part_of_default_test_discovery(self):
        self.assertFalse(fnmatch.fnmatch("release_test_public_policy.py", "test*.py"))
        self.assertTrue(fnmatch.fnmatch("release_test_public_policy.py", "release_test*.py"))

    def test_runtime_keeps_release_checks_out_of_public_profiles(self):
        runtime = load()
        self.assertEqual(runtime["stable"]["releaseCheckProfile"], "release")
        release_commands = runtime["quality"]["release"]
        self.assertEqual(len(release_commands), 1)
        self.assertIn("release_test*.py", release_commands[0])
        for profile in ("before", "after", "quick", "full"):
            flattened = " ".join(part for command in runtime["quality"][profile] for part in command)
            self.assertNotIn("release_test", flattened)

    def test_quality_command_accepts_internal_release_profile(self):
        config = {
            "quality": {
                "release": [["{python}", "release-check"]],
            }
        }
        environment = {
            "ready": True,
            "python": "/tmp/python",
            "dependencies": {},
        }
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            log = root / ".flow/state/logs/release.log"
            with patch.object(quality_command, "inspect_project_environment", return_value=environment), patch.object(
                quality_command, "run_logged", return_value=log
            ) as run_logged, patch.object(quality_command, "git", return_value="identity"):
                result = quality_command.run(root, ["--release"], config, None)
        self.assertEqual(result["exitCode"], 0)
        self.assertIn("release 检查通过", result["current"])
        run_logged.assert_called_once_with(root, config["quality"]["release"][0], "quality-release-1")

    def test_stable_preview_runs_release_policy_profile(self):
        config = {"stable": {"releaseCheckProfile": "release"}}
        with patch.object(stable_command, "run_check", return_value={"exitCode": 0}) as run_check:
            stable_command._run_release_policy_check(Path("/tmp/project"), config)
        run_check.assert_called_once_with(
            Path("/tmp/project"), ["--release", "--machine"], config, None
        )

    def test_stable_preview_rejects_failed_release_policy(self):
        config = {"stable": {"releaseCheckProfile": "release"}}
        with patch.object(stable_command, "run_check", return_value={"exitCode": 1}):
            with self.assertRaisesRegex(stable_command.StableReleaseError, "公开发布策略检查未通过"):
                stable_command._run_release_policy_check(Path("/tmp/project"), config)


if __name__ == "__main__":
    unittest.main()
