from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
DATA_SCHEMA = ROOT / "docs/public/DATA-SCHEMA.md"
DATA_LIFECYCLE = ROOT / "docs/public/DATA-LIFECYCLE.md"
ARCHITECTURE = ROOT / "docs/public/ARCHITECTURE.md"
RELEASE_NOTES = ROOT / "RELEASE-NOTES.md"
NPM_BETA = ROOT / "script/project/npm_beta.py"


class PublicDataPackageDocumentationTest(unittest.TestCase):
    def test_root_readme_distinguishes_template_candidate_and_artifact(self) -> None:
        text = README.read_text(encoding="utf-8")
        self.assertIn("`packages/kancolle-data/` 是受 Git 管理的 npm 源码模板", text)
        self.assertIn("`dist/packages/kancolle-data/`", text)
        self.assertIn("`dist/npm/kancolle-data/<version>/`", text)
        self.assertIn("cd dist/packages/kancolle-data", text)
        self.assertIn("require('./dist/packages/kancolle-data')", text)
        self.assertNotIn("数据包位于 `packages/kancolle-data/`", text)
        self.assertNotIn("cd packages/kancolle-data", text)
        self.assertNotIn("require('./packages/kancolle-data')", text)

    def test_schema_document_uses_generated_package_paths(self) -> None:
        text = DATA_SCHEMA.read_text(encoding="utf-8")
        self.assertIn(
            "`dist/packages/kancolle-data/compat/poi-plugin-item-improvement2/`",
            text,
        )
        self.assertIn("`dist/packages/kancolle-data/equipment/sources.nedb`", text)
        self.assertNotIn(
            "`packages/kancolle-data/compat/poi-plugin-item-improvement2/`",
            text,
        )
        self.assertNotIn("`packages/kancolle-data/equipment/sources.nedb`", text)

    def test_lifecycle_and_beta_builder_share_unified_npm_output_root(self) -> None:
        lifecycle = DATA_LIFECYCLE.read_text(encoding="utf-8")
        implementation = NPM_BETA.read_text(encoding="utf-8")
        self.assertIn("dist/npm/kancolle-data/<version>/", lifecycle)
        self.assertIn(
            'DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "dist" / "npm" / "kancolle-data"',
            implementation,
        )
        self.assertNotIn('PROJECT_ROOT / "dist" / "npm-beta"', implementation)

    def test_lifecycle_uses_current_main_for_frozen_source_bundles(self) -> None:
        text = DATA_LIFECYCLE.read_text(encoding="utf-8")
        self.assertIn("Data Build 始终使用当前 `main` 的代码", text)
        self.assertIn("采集 Commit 只用于来源追溯", text)
        self.assertIn("CACHE_ONLY/STRICT 构建明确拒绝", text)
        self.assertNotIn("Data Build 先用 Source Bundle 绑定的代码", text)
        self.assertNotIn("再切回当前 `main` 的发布控制器", text)

    def test_lifecycle_documents_delayed_npm_registry_reconciliation(self) -> None:
        text = DATA_LIFECYCLE.read_text(encoding="utf-8")
        self.assertIn("`--prefer-online`", text)
        self.assertIn("最长等待 120 秒", text)
        self.assertIn("按幂等成功继续后续变体", text)
        self.assertIn("错误尾部", text)

    def test_architecture_and_release_notes_use_the_same_three_stage_contract(self) -> None:
        architecture = ARCHITECTURE.read_text(encoding="utf-8")
        notes = RELEASE_NOTES.read_text(encoding="utf-8")
        for text in (architecture, notes):
            self.assertIn("packages/kancolle-data/", text)
            self.assertIn("dist/packages/kancolle-data/", text)
            self.assertIn("dist/npm/kancolle-data/<version>/", text)


if __name__ == "__main__":
    unittest.main()
