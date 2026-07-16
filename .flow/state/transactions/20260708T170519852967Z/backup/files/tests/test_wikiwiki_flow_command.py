from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from script.project import wikiwiki_command


def _make_root() -> tempfile.TemporaryDirectory:
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    config = root / "configs/wikiwiki-crawler.local.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"transport": "playwright", "userAgent": "ua", "acceptLanguage": "ja-JP"}) + "\n", encoding="utf-8")
    return temp


class WikiWikiFlowCommandTest(unittest.TestCase):
    def test_daily_flow_runs_catalog_then_crawl(self):
        with _make_root() as temp_name:
            root = Path(temp_name)
            calls: list[list[str]] = []

            def fake_run_logged(_root, command, label):
                calls.append(list(command))
                return root / f".flow/state/logs/{label}.log"

            with mock.patch.object(wikiwiki_command, "run_logged", side_effect=fake_run_logged):
                result = wikiwiki_command.run(root, [], {}, None)

            self.assertEqual(result["exitCode"], 0)
            self.assertEqual(len(calls), 2)
            self.assertIn("catalog", calls[0])
            self.assertIn("--kind", calls[0])
            self.assertIn("all", calls[0])
            self.assertIn("crawl", calls[1])
            self.assertNotIn("--refresh", calls[0])
            self.assertNotIn("--daily-limit", calls[1])
            self.assertIn("./flow run", result["next"])
            self.assertIn("三索引", "\n".join(result["completed"]))

    def test_full_flow_refreshes_catalog_and_uses_full_limit(self):
        with _make_root() as temp_name:
            root = Path(temp_name)
            calls: list[list[str]] = []

            def fake_run_logged(_root, command, label):
                calls.append(list(command))
                if label == "wikiwiki-crawl":
                    receipt = root / ".flow/local/wikiwiki-crawler/source-receipt.json"
                    receipt.parent.mkdir(parents=True, exist_ok=True)
                    receipt.write_text(json.dumps({"ready": True, "details": {"equipment": {"status": "ready"}, "ship": {"status": "deferred"}}}), encoding="utf-8")
                return root / f".flow/state/logs/{label}.log"

            with mock.patch.object(wikiwiki_command, "run_logged", side_effect=fake_run_logged):
                result = wikiwiki_command.run(root, ["--full"], {}, None)

            self.assertEqual(result["exitCode"], 0)
            self.assertIn("--refresh", calls[0])
            self.assertNotIn("--refresh", calls[1])
            index = calls[1].index("--daily-limit")
            self.assertEqual(calls[1][index + 1], str(wikiwiki_command.FULL_REFRESH_LIMIT))


    def test_smoke_flow_runs_three_item_chain_without_claiming_ready(self):
        with _make_root() as temp_name:
            root = Path(temp_name)
            calls: list[list[str]] = []

            def fake_run_logged(_root, command, label):
                calls.append(list(command))
                if label == "wikiwiki-crawl":
                    receipt = root / ".flow/local/wikiwiki-crawler/source-receipt.json"
                    receipt.parent.mkdir(parents=True, exist_ok=True)
                    receipt.write_text(json.dumps({
                        "ready": False,
                        "details": {
                            "equipment": {"status": "incomplete", "remaining": 568, "failed": 0, "stopReason": None},
                            "ship": {"status": "deferred"},
                        },
                    }), encoding="utf-8")
                return root / f".flow/state/logs/{label}.log"

            with mock.patch.object(wikiwiki_command, "run_logged", side_effect=fake_run_logged):
                result = wikiwiki_command.run(root, ["smoke"], {}, None)

            self.assertEqual(result["exitCode"], 0)
            self.assertIn("catalog", calls[0])
            self.assertIn("crawl", calls[1])
            index = calls[1].index("--daily-limit")
            self.assertEqual(calls[1][index + 1], "3")
            self.assertIn("3 条数据链路验证", result["current"])
            self.assertIn("receipt ready 后再执行 ./flow run", result["next"])

    def test_smoke_rejects_full_flag(self):
        with _make_root() as temp_name:
            root = Path(temp_name)
            result = wikiwiki_command.run(root, ["smoke", "--full"], {}, None)

            self.assertEqual(result["exitCode"], 2)
            self.assertIn("smoke", result["current"])

    def test_session_runs_only_session_command(self):
        with _make_root() as temp_name:
            root = Path(temp_name)
            calls: list[list[str]] = []

            def fake_run_logged(_root, command, label):
                calls.append(list(command))
                return root / f".flow/state/logs/{label}.log"

            with mock.patch.object(wikiwiki_command, "run_logged", side_effect=fake_run_logged):
                result = wikiwiki_command.run(root, ["session"], {}, None)

            self.assertEqual(result["exitCode"], 0)
            self.assertEqual(len(calls), 1)
            self.assertIn("session", calls[0])

    def test_missing_config_is_materialized_from_template_and_stops_for_review(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            template = root / "configs/wikiwiki-crawler.default.json"
            template.parent.mkdir(parents=True, exist_ok=True)
            template.write_text(json.dumps({"transport": "playwright", "browserHeadless": True}) + "\n", encoding="utf-8")

            result = wikiwiki_command.run(root, [], {}, None)

            self.assertEqual(result["exitCode"], 2)
            self.assertTrue((root / "configs/wikiwiki-crawler.local.json").is_file())
            self.assertEqual(
                template.read_text(encoding="utf-8"),
                (root / "configs/wikiwiki-crawler.local.json").read_text(encoding="utf-8"),
            )
            self.assertIn("已生成", result["current"])
            self.assertIn("configs/wikiwiki-crawler.local.json", "\n".join(result["completed"]))
            self.assertIn("configs/wikiwiki-crawler.default.json", "\n".join(result["completed"]))
            logs = list((root / ".flow/state/logs").glob("*-wikiwiki-config.log"))
            self.assertEqual(1, len(logs))
            self.assertIn("WikiWiki local config materialized", logs[0].read_text(encoding="utf-8"))

    def test_config_action_reports_existing_local_config(self):
        with _make_root() as temp_name:
            root = Path(temp_name)
            result = wikiwiki_command.run(root, ["config"], {}, None)

            self.assertEqual(result["exitCode"], 0)
            self.assertIn("已存在", result["current"])
            self.assertIn("configs/wikiwiki-crawler.local.json", "\n".join(result["completed"]))

    def test_config_action_materializes_local_config(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            template = root / "configs/wikiwiki-crawler.default.json"
            template.parent.mkdir(parents=True, exist_ok=True)
            template.write_text(json.dumps({"transport": "playwright"}) + "\n", encoding="utf-8")

            result = wikiwiki_command.run(root, ["config"], {}, None)

            self.assertEqual(result["exitCode"], 2)
            self.assertTrue((root / "configs/wikiwiki-crawler.local.json").is_file())
            self.assertIn("需确认后重跑", result["current"])


    def test_config_action_migrates_legacy_flow_local_config(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            default = root / "configs/wikiwiki-crawler.default.json"
            default.parent.mkdir(parents=True, exist_ok=True)
            default.write_text(json.dumps({"transport": "playwright", "browserHeadless": True}) + "\n", encoding="utf-8")
            legacy = root / ".flow/local/wikiwiki-curl.json"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_text(json.dumps({"transport": "playwright", "browserHeadless": False}) + "\n", encoding="utf-8")

            result = wikiwiki_command.run(root, ["config"], {}, None)

            self.assertEqual(result["exitCode"], 2)
            local = root / "configs/wikiwiki-crawler.local.json"
            self.assertTrue(local.is_file())
            self.assertEqual(legacy.read_text(encoding="utf-8"), local.read_text(encoding="utf-8"))
            self.assertIn("已从旧路径迁移", "\n".join(result["completed"]))

    def test_missing_template_is_clear_failure_and_writes_log(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            result = wikiwiki_command.run(root, [], {}, None)

            self.assertEqual(result["exitCode"], 2)
            self.assertIn("缺少 WikiWiki 默认配置", result["current"])
            self.assertIn("configs/wikiwiki-crawler.default.json", "\n".join(result["incomplete"]))
            logs = list((root / ".flow/state/logs").glob("*-wikiwiki-config.log"))
            self.assertEqual(1, len(logs))
            self.assertIn("WikiWiki config bootstrap failed", logs[0].read_text(encoding="utf-8"))

    def test_daily_flow_does_not_suggest_run_when_receipt_incomplete(self):
        with _make_root() as temp_name:
            root = Path(temp_name)

            def fake_run_logged(_root, command, label):
                if label == "wikiwiki-crawl":
                    receipt = root / ".flow/local/wikiwiki-crawler/source-receipt.json"
                    receipt.parent.mkdir(parents=True, exist_ok=True)
                    receipt.write_text(json.dumps({
                        "ready": False,
                        "details": {
                            "equipment": {"status": "incomplete", "remaining": 12, "failed": 0, "stopReason": None},
                            "ship": {"status": "deferred"},
                        },
                    }), encoding="utf-8")
                return root / f".flow/state/logs/{label}.log"

            with mock.patch.object(wikiwiki_command, "run_logged", side_effect=fake_run_logged):
                result = wikiwiki_command.run(root, [], {}, None)

            self.assertEqual(result["exitCode"], 0)
            self.assertIn("source receipt 尚未 ready", result["current"])
            self.assertIn("receipt ready 后再执行 ./flow run", result["next"])

    def test_full_flow_rejects_incomplete_detail_receipt(self):
        with _make_root() as temp_name:
            root = Path(temp_name)

            def fake_run_logged(_root, command, label):
                if label == "wikiwiki-crawl":
                    receipt = root / ".flow/local/wikiwiki-crawler/source-receipt.json"
                    receipt.parent.mkdir(parents=True, exist_ok=True)
                    receipt.write_text(json.dumps({
                        "ready": False,
                        "details": {
                            "equipment": {"status": "incomplete", "remaining": 2, "failed": 0, "stopReason": None},
                            "ship": {"status": "deferred"},
                        },
                    }), encoding="utf-8")
                return root / f".flow/state/logs/{label}.log"

            with mock.patch.object(wikiwiki_command, "run_logged", side_effect=fake_run_logged):
                result = wikiwiki_command.run(root, ["--full"], {}, None)

            self.assertEqual(result["exitCode"], 75)
            self.assertIn("remaining=2", "\n".join(result["incomplete"]))
            self.assertIn("不要先执行 ./flow run", result["next"])

    def test_source_does_not_publish_or_push(self):
        source = Path(wikiwiki_command.__file__).read_text(encoding="utf-8")
        self.assertNotIn("git push", source)
        self.assertNotIn("npm publish", source)


if __name__ == "__main__":
    unittest.main()
