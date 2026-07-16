from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FlowCommandTest(unittest.TestCase):
    def run_flow(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "flow", *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=check,
        )

    def test_help_only_exposes_public_commands_and_project_tool_boundary(self):
        completed = self.run_flow("help")
        self.assertIn("公共命令", completed.stdout)
        self.assertIn("./flow status", completed.stdout)
        self.assertIn("./flow run-wikiwiki-source", completed.stdout)
        self.assertIn("项目内部构建、npm、数据诊断命令", completed.stdout)
        self.assertNotIn("update:inspect", completed.stdout)
        self.assertNotIn("quality:full", completed.stdout)

    def test_human_output_has_fixed_sections(self):
        completed = self.run_flow("status")
        for label in ("结果：", "当前状态：", "完成内容：", "未完成内容：", "下一步：", "恢复方式："):
            self.assertIn(label, completed.stdout)

    def test_default_flow_is_active_navigator_not_large_menu(self):
        completed = self.run_flow()
        self.assertIn("下一步：", completed.stdout)
        self.assertNotIn("请选择", completed.stdout)

    def test_machine_status_is_single_contract_json_document(self):
        completed = self.run_flow("status", "--json")
        value = json.loads(completed.stdout)
        self.assertEqual(value["schemaVersion"], 1)
        self.assertEqual(value["projectId"], "kancolle-item-improvement-spider")
        self.assertEqual(value["command"], "status")
        self.assertEqual(value["result"], "success")
        self.assertEqual(value["exitCode"], 0)
        self.assertEqual(completed.stderr, "")

    def test_capabilities_match_public_contract(self):
        completed = self.run_flow("capabilities", "--json")
        value = json.loads(completed.stdout)
        self.assertEqual(value["contract"], {"id": "flow.public", "version": "1.1.0"})
        self.assertEqual(
            value["capabilities"],
            {"flow.command": True, "update.transaction": True, "recovery.package": True},
        )
        self.assertEqual(value["flowPackage"]["implementation"], "embedded-spider-flow")
        self.assertEqual(value["flowPackage"]["supportedContracts"], {"flow.public": ["1.1.0"]})
        self.assertRegex(value["flowPackage"]["version"], r"^1\.1\.0-spider\.\d+$")
        self.assertEqual(value["commands"]["wikiwiki"]["sideEffect"], "L2")
        self.assertEqual(value["commands"]["run-wikiwiki-source"]["sideEffect"], "L2")
        self.assertEqual(value["commands"]["push"]["sideEffect"], "L3")
        self.assertEqual(value["commands"]["stable"]["sideEffect"], "L4")
        self.assertFalse(value["commands"]["beta"]["supported"])
        self.assertTrue(value["commands"]["beta"]["reason"])

    def test_non_interactive_remote_write_requires_one_confirmation(self):
        completed = self.run_flow("stable", "--non-interactive", "--json", check=False)
        value = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 40)
        self.assertEqual(value["result"], "confirmation-required")
        self.assertTrue(value["nextAction"])


if __name__ == "__main__":
    unittest.main()
