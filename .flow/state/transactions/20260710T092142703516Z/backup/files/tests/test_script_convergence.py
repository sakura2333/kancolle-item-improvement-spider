from __future__ import annotations

import ast
import importlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text("utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


class FlowConvergenceTest(unittest.TestCase):
    def test_no_old_control_semantics_or_parallel_entrypoints(self):
        self.assertFalse((ROOT / ".devops").exists())
        self.assertFalse((ROOT / "script/project_flow.py").exists())
        retired = ROOT / "script/flow_tasks"
        self.assertEqual(list(retired.glob("*.py")) + list(retired.glob("*.md")), [])

        legacy_modules = ("project_devops", "script.infra_adapter", "script.infra_capabilities")
        hits = []
        for path in (ROOT / "script").rglob("*.py"):
            if any(
                module == prefix or module.startswith(prefix + ".")
                for module in imported_modules(path)
                for prefix in legacy_modules
            ):
                hits.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(hits, [])

        self.assertTrue((ROOT / "flow").is_file())
        self.assertTrue((ROOT / "flow.cmd").is_file())
        parallel = [
            path.name
            for pattern in ("*.command", "*.cmd")
            for path in ROOT.glob(pattern)
            if path.name != "flow.cmd"
        ]
        self.assertEqual(parallel, [])

    def test_layer_dependencies_are_one_way(self):
        # Business/data code must not depend on Flow or project engineering tools.
        business_hits: list[str] = []
        for base in (ROOT / "service", ROOT / "util", ROOT / "pojo", ROOT / "configs"):
            for path in base.rglob("*.py"):
                modules = imported_modules(path)
                if any(module.startswith("script.flow") or module.startswith("script.project") for module in modules):
                    business_hits.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(business_hits, [])

        # Project tools may not depend on the Flow implementation.
        project_hits: list[str] = []
        for path in (ROOT / "script/project").rglob("*.py"):
            if any(module.startswith("script.flow") for module in imported_modules(path)):
                project_hits.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(project_hits, [])

        # Adapter is the only project-specific module imported by Flow CLI.
        cli_modules = imported_modules(ROOT / "script/flow/cli.py")
        self.assertIn("script", cli_modules)
        text = (ROOT / "script/flow/cli.py").read_text("utf-8")
        self.assertIn("from script import flow_adapter", text)
        self.assertNotIn("script.project", text)

    def test_update_and_recovery_are_loaded_only_when_called(self):
        for name in ("script.flow.cli", "script.flow.update", "script.flow.recovery"):
            sys.modules.pop(name, None)
        cli = importlib.import_module("script.flow.cli")
        self.assertNotIn("script.flow.update", sys.modules)
        self.assertNotIn("script.flow.recovery", sys.modules)
        cli._capability_module("update")
        self.assertIn("script.flow.update", sys.modules)
        self.assertNotIn("script.flow.recovery", sys.modules)

    def test_only_one_public_binding_and_thin_adapter(self):
        binding = json.loads((ROOT / ".flow/project.json").read_text("utf-8"))
        self.assertEqual(
            set(binding),
            {"projectId", "contract", "versionSource", "maintenanceProfile", "publicReleasePolicy"},
        )
        self.assertTrue((ROOT / "script/flow_adapter.py").is_file())
        self.assertTrue((ROOT / "script/project/cli.py").is_file())
        duplicate_configs = list(ROOT.glob("**/flow-runtime.json")) + list(ROOT.glob("**/project-flow.json"))
        self.assertEqual(duplicate_configs, [])


if __name__ == "__main__":
    unittest.main()
