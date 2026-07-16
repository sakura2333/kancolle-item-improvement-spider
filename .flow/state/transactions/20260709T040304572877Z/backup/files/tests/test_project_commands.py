from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "script/project"


def _load(name: str, file: str):
    sys.path.insert(0, str(PROJECT))
    try:
        spec = importlib.util.spec_from_file_location(name, PROJECT / file)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


class ProjectCommandContractTest(unittest.TestCase):
    def setUp(self):
        self.binding = json.loads((ROOT / ".flow/project.json").read_text("utf-8"))
        from script import flow_adapter
        self.runtime = flow_adapter.runtime(ROOT, self.binding)

    def test_bound_contract_is_exact_and_immutable(self):
        contract = self.binding["contract"]
        self.assertEqual(contract["id"], "flow.public")
        self.assertEqual(contract["version"], "1.1.0")
        self.assertEqual(contract["repository"], "http://192.168.1.129:13000/personal/infra-flow-contract-temp")
        self.assertRegex(contract["commit"], r"^[0-9a-f]{40}$")
        self.assertRegex(contract["contractSha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(self.binding["versionSource"], {"type": "file", "value": "VERSION"})

    def test_human_interface_and_side_effects_are_fixed(self):
        self.assertEqual(
            self.runtime["humanCommands"],
            ["status", "check", "smoke", "run", "wikiwiki", "push", "beta", "stable", "package", "update-package", "update", "rollback"],
        )
        self.assertEqual(self.runtime["publicCapabilities"]["wikiwiki"]["sideEffect"], "L2")
        self.assertEqual(self.runtime["publicCapabilities"]["push"]["sideEffect"], "L3")
        self.assertEqual(self.runtime["publicCapabilities"]["stable"]["sideEffect"], "L4")
        self.assertFalse(self.runtime["publicCapabilities"]["beta"]["supported"])

    def test_only_three_public_capabilities_are_enabled(self):
        self.assertEqual(
            self.runtime["capabilities"],
            {"flow.command": True, "update.transaction": True, "recovery.package": True},
        )
        self.assertEqual(self.runtime["update"]["requiredBranch"], "dev")
        self.assertIn(".flow/local.json", self.runtime["update"]["protected"])
        self.assertEqual(self.runtime["update"]["identityProvider"], "script.project.ownership:identity_value")
        self.assertTrue(self.runtime["update"]["autoCommit"])
        self.assertTrue(self.runtime["update"]["autoCommitRollback"])

    def test_code_candidate_check_allows_generated_manifest_version_lag(self):
        checks = _load("spider_project_checks", "_project_checks.py")
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            package = root / "packages/kancolle-data"
            package.mkdir(parents=True)
            (root / "VERSION").write_text("1.0.12\n", encoding="utf-8")
            (package / "package.json").write_text(
                json.dumps({"version": "0.4.0"}) + "\n", encoding="utf-8"
            )
            (package / "manifest.json").write_text(
                json.dumps({"packageVersion": "0.3.0"}) + "\n", encoding="utf-8"
            )
            original_root = checks.PROJECT_ROOT
            original_package = checks.PACKAGE_DIR
            try:
                checks.PROJECT_ROOT = root
                checks.PACKAGE_DIR = package
                checks.verify_versions(include_generated_state=False)
                with self.assertRaises(checks.ProjectCommandError):
                    checks.verify_versions(include_generated_state=True)
            finally:
                checks.PROJECT_ROOT = original_root
                checks.PACKAGE_DIR = original_package

    def test_project_check_accepts_single_control_plane(self):
        check = _load("spider_check", "check.py")
        check.execute("before")
        check.execute(include_generated_state=False)
        verify = _load("spider_verify", "verify.py")
        verify._verify_versions(include_generated_state=False)
        verify._verify_generated_state_contract()
        verify._verify_automation_contract()


if __name__ == "__main__":
    unittest.main()
