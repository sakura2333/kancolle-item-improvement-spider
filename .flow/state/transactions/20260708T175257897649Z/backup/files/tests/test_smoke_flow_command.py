from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from script.project import smoke_command


class SmokeFlowCommandTest(unittest.TestCase):
    def test_full_chain_smoke_runs_before_start2_then_wikiwiki_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            calls: list[tuple[str, list[str]]] = []

            def fake_run_logged(_root, command, label):
                calls.append((label, list(command)))
                return root / f".flow/state/logs/{label}.log"

            with mock.patch.object(smoke_command, "run_logged", side_effect=fake_run_logged):
                result = smoke_command.run(root, [], {}, None)

            self.assertEqual(result["exitCode"], 0)
            self.assertEqual([label for label, _ in calls], [
                "smoke-before-check",
                "smoke-start2",
                "smoke-wikiwiki-probe",
            ])
            self.assertIn("check.py", " ".join(calls[0][1]))
            self.assertIn("start2_command.py", " ".join(calls[1][1]))
            self.assertIn("wikiwiki", calls[2][1])
            self.assertIn("probe", calls[2][1])
            self.assertIn("--daily-limit", calls[2][1])
            self.assertIn("3", calls[2][1])
            self.assertIn("Start2", result["current"])
            self.assertIn("not-ready", "\n".join(result["incomplete"]))

    def test_smoke_rejects_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            result = smoke_command.run(Path(temp_name), ["--full"], {}, None)
            self.assertEqual(result["exitCode"], 2)
            self.assertIn("不接受", result["current"])


if __name__ == "__main__":
    unittest.main()
