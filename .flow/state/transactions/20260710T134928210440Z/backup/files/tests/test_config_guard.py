from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from script.project.config_guard import verify_config_governance
from script.project._common import ProjectCommandError


class ConfigGovernanceTest(unittest.TestCase):
    def _root(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory()

    def _write(self, root: Path, relative: str, text: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_committed_default_configs_are_allowed(self) -> None:
        with self._root() as directory:
            root = Path(directory)
            self._write(root, "configs/wikiwiki-crawler.default.json", json.dumps({"cookie": "", "browserProfileDir": ".flow/local/profile"}))
            verify_config_governance(root)

    def test_tool_config_example_must_move_to_configs_default(self) -> None:
        with self._root() as directory:
            root = Path(directory)
            self._write(root, "tools/wikiwiki-crawler/config.example.json", "{}")
            with self.assertRaisesRegex(ProjectCommandError, "configs/.*default"):
                verify_config_governance(root)

    def test_private_config_is_rejected_even_under_configs(self) -> None:
        with self._root() as directory:
            root = Path(directory)
            self._write(root, "configs/wikiwiki.private.json", "{}")
            with self.assertRaisesRegex(ProjectCommandError, "本地/私密配置"):
                verify_config_governance(root)

    def test_non_template_config_rejects_local_absolute_paths(self) -> None:
        with self._root() as directory:
            root = Path(directory)
            self._write(root, "configs/source-policy.json", '{"path":"/Users/sakana/secret"}')
            with self.assertRaisesRegex(ProjectCommandError, "本机绝对路径"):
                verify_config_governance(root)

    def test_non_template_config_rejects_placeholders(self) -> None:
        with self._root() as directory:
            root = Path(directory)
            self._write(root, "configs/source-policy.json", '{"token":"__TOKEN__"}')
            with self.assertRaisesRegex(ProjectCommandError, "占位符"):
                verify_config_governance(root)

    def test_configs_readme_is_required_but_not_json_contract(self) -> None:
        from script.project._project_checks import JSON_CONTRACT_FILES, PROJECT_ROOT, REQUIRED_PATHS

        readme = PROJECT_ROOT / "configs" / "README.md"
        self.assertIn(readme, REQUIRED_PATHS)
        self.assertNotIn(readme, JSON_CONTRACT_FILES)

    def test_tracked_generated_data_json_is_not_treated_as_config_placeholder(self) -> None:
        with self._root() as directory:
            root = Path(directory)
            self._write(root, ".flow/local/source-cache/example.json", '{"text":"__DOMAIN_PLACEHOLDER__"}')
            verify_config_governance(root)


if __name__ == "__main__":
    unittest.main()
