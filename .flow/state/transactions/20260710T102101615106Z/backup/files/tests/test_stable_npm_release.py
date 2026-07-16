from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from script.project import stable_command


_RELEASE_SET = {
    "artifacts": [
        {
            "variant": "current",
            "package": "@sakura2333/kancolle-data",
            "version": "0.5.1",
            "distTag": "latest",
            "tarball": "/tmp/current.tgz",
            "packageResult": "current.package-result.json",
        },
        {
            "variant": "improvement2",
            "package": "@sakura2333/kancolle-data",
            "version": "0.5.1-improvement2",
            "distTag": "improvement2",
            "tarball": "/tmp/improvement2.tgz",
            "packageResult": "improvement2.package-result.json",
        },
    ]
}


class StableNpmReleaseTest(unittest.TestCase):
    def test_missing_versions_produce_both_manual_publish_commands(self):
        def fake_reconcile(**kwargs):
            tag = kwargs["tag"]
            version = "0.5.1" if tag == "latest" else "0.5.1-improvement2"
            return {"status": "ready-not-published", "tag": tag, "version": version}

        with tempfile.TemporaryDirectory() as temp_name, patch.object(
            stable_command, "reconcile_npm_publish", side_effect=fake_reconcile
        ):
            complete, audits, commands = stable_command._inspect_npm_release(
                Path(temp_name), _RELEASE_SET
            )
        self.assertFalse(complete)
        self.assertEqual(len(audits), 2)
        self.assertEqual(len(commands), 2)
        self.assertIn("--tag latest", commands[0])
        self.assertIn("--tag improvement2", commands[1])

    def test_exact_versions_and_tags_complete_the_stable_candidate(self):
        def fake_reconcile(**kwargs):
            tag = kwargs["tag"]
            version = "0.5.1" if tag == "latest" else "0.5.1-improvement2"
            return {
                "status": "already-published",
                "tag": tag,
                "version": version,
                "distTag": {"after": version},
            }

        with tempfile.TemporaryDirectory() as temp_name, patch.object(
            stable_command, "reconcile_npm_publish", side_effect=fake_reconcile
        ):
            complete, audits, commands = stable_command._inspect_npm_release(
                Path(temp_name), _RELEASE_SET
            )
        self.assertTrue(complete)
        self.assertEqual(len(audits), 2)
        self.assertEqual(commands, [])


if __name__ == "__main__":
    unittest.main()
