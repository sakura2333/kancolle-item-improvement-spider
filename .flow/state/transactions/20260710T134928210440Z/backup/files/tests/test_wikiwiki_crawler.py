from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = ROOT / "automation" / "acquire" / "wikiwiki"
sys.path.insert(0, str(TOOL_DIR))
spec = importlib.util.spec_from_file_location("wikiwiki_crawler_test_module", TOOL_DIR / "crawler.py")
assert spec and spec.loader
crawler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crawler)


class WikiWikiCrawlerTest(unittest.TestCase):
    def test_resume_skips_do_not_consume_daily_limit(self):
        with tempfile.TemporaryDirectory() as temp_name:
            project = Path(temp_name)
            (project / "configs").mkdir(parents=True)
            config = project / "configs/wikiwiki-crawler.local.json"
            config.write_text(json.dumps({
                "userAgent": "test-agent",
                "acceptLanguage": "ja-JP",
                "cookie": "session=valid",
                "delaySeconds": 0,
                "delayJitterSeconds": 0,
                "maxTransientRetries": 0,
                "maxRateLimitRetries": 0,
                "maxConsecutiveRateLimits": 1,
            }), encoding="utf-8")
            start2 = project / "items.json"
            start2.write_text(json.dumps([
                {"api_id": 1, "api_sortno": 1, "api_name": "A"},
                {"api_id": 2, "api_sortno": 2, "api_name": "B"},
                {"api_id": 3, "api_sortno": 3, "api_name": "C"},
            ]), encoding="utf-8")
            aliases = project / "aliases.json"
            aliases.write_text(json.dumps({
                "schemaVersion": 1,
                "reviewStatus": "accepted",
                "aliases": [],
            }), encoding="utf-8")
            catalog = project / "catalog.json"
            catalog.write_text(json.dumps({"kind": "equipment", "entries": []}), encoding="utf-8")
            output = project / "state"
            raw_root = project / "raw"

            first_url = "https://wikiwiki.jp/kancolle/A"
            first_raw = crawler.url_to_cache_path(raw_root, first_url)
            first_raw.parent.mkdir(parents=True)
            first_raw.write_text("<html>" + "x" * 300 + " No. 1</html>", encoding="utf-8")
            first_sha = crawler.sha256_file(first_raw)
            output.mkdir(parents=True)
            (output / "records.json").write_text(json.dumps({
                "schemaVersion": 1,
                "records": {
                    "1": {"status": "saved", "sha256": first_sha}
                },
            }), encoding="utf-8")

            def resolve(item, _catalog, _aliases):
                name = item["equipmentName"]
                return {
                    "status": "resolved",
                    "url": f"https://wikiwiki.jp/kancolle/{name}",
                    "matchType": "test",
                    "wikiName": name,
                }

            calls: list[str] = []

            def fake_curl(*, config, url, output_path, state_dir):
                calls.append(url)
                equipment_id = 2 if url.endswith("/B") else 3
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    "<html>" + "x" * 300 + f" No. {equipment_id}</html>",
                    encoding="utf-8",
                )
                return 0, 200, ""

            args = argparse.Namespace(
                project=project,
                config=Path("configs/wikiwiki-crawler.local.json"),
                output=Path("state"),
                raw_root=Path("raw"),
                start2=Path("items.json"),
                name_aliases=Path("aliases.json"),
                catalog=Path("catalog.json"),
                equipment_ids=None,
                from_id=None,
                daily_limit=1,
                limit=None,
                refresh=False,
            )
            with mock.patch.object(crawler, "item_url", side_effect=resolve), mock.patch.object(
                crawler, "run_curl", side_effect=fake_curl
            ):
                exit_code = crawler.crawl_command(args)

            self.assertEqual(exit_code, 0)
            self.assertEqual(calls, ["https://wikiwiki.jp/kancolle/B"])
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["skipped"], 1)
            self.assertEqual(summary["attempted"], 1)
            self.assertTrue(summary["quotaReached"])
            self.assertEqual(summary["nextEquipmentId"], 3)


    def test_config_daily_limit_is_used_when_cli_omitted(self):
        with tempfile.TemporaryDirectory() as temp_name:
            project = Path(temp_name)
            (project / "configs").mkdir(parents=True)
            config = project / "configs/wikiwiki-crawler.local.json"
            config.write_text(json.dumps({
                "userAgent": "test-agent",
                "acceptLanguage": "ja-JP",
                "cookie": "session=valid",
                "dailyLimit": 2,
                "delaySeconds": 0,
                "delayJitterSeconds": 0,
                "maxTransientRetries": 0,
                "maxRateLimitRetries": 0,
                "maxConsecutiveRateLimits": 1,
            }), encoding="utf-8")
            start2 = project / "items.json"
            start2.write_text(json.dumps([
                {"api_id": 1, "api_sortno": 1, "api_name": "A"},
                {"api_id": 2, "api_sortno": 2, "api_name": "B"},
                {"api_id": 3, "api_sortno": 3, "api_name": "C"},
            ]), encoding="utf-8")
            aliases = project / "aliases.json"
            aliases.write_text(json.dumps({
                "schemaVersion": 1,
                "reviewStatus": "accepted",
                "aliases": [],
            }), encoding="utf-8")
            catalog = project / "catalog.json"
            catalog.write_text(json.dumps({"kind": "equipment", "entries": []}), encoding="utf-8")
            output = project / "state"

            def resolve(item, _catalog, _aliases):
                name = item["equipmentName"]
                return {
                    "status": "resolved",
                    "url": f"https://wikiwiki.jp/kancolle/{name}",
                    "matchType": "test",
                    "wikiName": name,
                }

            calls: list[str] = []

            def fake_curl(*, config, url, output_path, state_dir):
                calls.append(url)
                equipment_id = len(calls)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    "<html>" + "x" * 300 + f" No. {equipment_id}</html>",
                    encoding="utf-8",
                )
                return 0, 200, ""

            args = argparse.Namespace(
                project=project,
                config=Path("configs/wikiwiki-crawler.local.json"),
                output=Path("state"),
                raw_root=Path("raw"),
                start2=Path("items.json"),
                name_aliases=Path("aliases.json"),
                catalog=Path("catalog.json"),
                equipment_ids=None,
                from_id=None,
                daily_limit=None,
                limit=None,
                refresh=False,
            )
            with mock.patch.object(crawler, "item_url", side_effect=resolve), mock.patch.object(
                crawler, "run_curl", side_effect=fake_curl
            ):
                exit_code = crawler.crawl_command(args)

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(calls), 2)
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["dailyLimit"], 2)
            self.assertTrue(summary["quotaReached"])

    def test_cli_daily_limit_overrides_config_daily_limit(self):
        config = crawler.validate_config({
            "transport": "playwright",
            "userAgent": "test-agent",
            "acceptLanguage": "ja-JP",
            "dailyLimit": 2,
        })
        self.assertEqual(config["dailyLimit"], 2)

    def test_playwright_config_does_not_require_copied_cookie(self):
        config = crawler.validate_config({
            "transport": "playwright",
            "userAgent": "test-agent",
            "acceptLanguage": "ja-JP",
        })
        self.assertEqual(config["transport"], "playwright")
        self.assertEqual(config["dailyLimit"], 40)
        self.assertEqual(config["maxAgeDays"], 15)
        self.assertEqual(config["catalogMaxAgeHours"], 46)

    def test_stale_capture_is_not_resumable(self):
        with tempfile.TemporaryDirectory() as temp_name:
            raw = Path(temp_name) / "page.html"
            raw.write_text("<html>" + "x" * 300 + "</html>", encoding="utf-8")
            record = {
                "status": "saved",
                "sha256": crawler.sha256_file(raw),
                "fetchedAt": "2020-01-01T00:00:00+00:00",
            }
            self.assertFalse(crawler.is_resumable_record(record, raw, max_age_days=20))

    def test_request_dispatches_to_playwright_transport(self):
        config = crawler.validate_config({
            "transport": "playwright",
            "userAgent": "test-agent",
            "acceptLanguage": "ja-JP",
        })
        with tempfile.TemporaryDirectory() as temp_name, mock.patch.object(
            crawler, "run_playwright", return_value=(0, 200, "")
        ) as fetch:
            temp = Path(temp_name)
            result = crawler.run_request(
                config=config,
                url="https://wikiwiki.jp/kancolle/",
                output_path=temp / "page.html",
                state_dir=temp / "state",
                project=temp,
            )
        self.assertEqual(result, (0, 200, ""))
        fetch.assert_called_once()

    def test_source_page_number_mismatch_is_diagnostic_not_identity_gate(self):
        with tempfile.TemporaryDirectory() as temp_name:
            project = Path(temp_name)
            (project / ".flow/local").mkdir(parents=True)
            (project / "configs").mkdir(parents=True, exist_ok=True)
            (project / "configs/wikiwiki-crawler.local.json").write_text(json.dumps({
                "userAgent": "test-agent",
                "acceptLanguage": "ja-JP",
                "cookie": "session=valid",
                "dailyLimit": 1,
                "delaySeconds": 0,
                "delayJitterSeconds": 0,
                "maxTransientRetries": 0,
                "maxRateLimitRetries": 0,
                "maxConsecutiveRateLimits": 1,
            }), encoding="utf-8")
            (project / "items.json").write_text(json.dumps([
                {"api_id": 1, "api_sortno": 1, "api_name": "A"},
            ]), encoding="utf-8")
            (project / "aliases.json").write_text(json.dumps({
                "schemaVersion": 1,
                "reviewStatus": "accepted",
                "aliases": [],
            }), encoding="utf-8")
            (project / "catalog.json").write_text(json.dumps({"kind": "equipment", "entries": []}), encoding="utf-8")

            def resolve(item, _catalog, _aliases):
                return {
                    "status": "resolved",
                    "url": "https://wikiwiki.jp/kancolle/A",
                    "matchType": "test",
                    "wikiName": item["equipmentName"],
                }

            def fake_curl(*, config, url, output_path, state_dir):
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text("<html>" + "x" * 300 + " No. 999</html>", encoding="utf-8")
                return 0, 200, ""

            args = argparse.Namespace(
                project=project,
                config=Path("configs/wikiwiki-crawler.local.json"),
                output=Path("state"),
                raw_root=Path("raw"),
                start2=Path("items.json"),
                name_aliases=Path("aliases.json"),
                catalog=Path("catalog.json"),
                equipment_ids=None,
                from_id=None,
                daily_limit=None,
                limit=None,
                refresh=False,
            )
            with mock.patch.object(crawler, "item_url", side_effect=resolve), mock.patch.object(
                crawler, "run_curl", side_effect=fake_curl
            ):
                exit_code = crawler.crawl_command(args)

            self.assertEqual(exit_code, 0)
            summary = json.loads((project / "state/summary.json").read_text(encoding="utf-8"))
            self.assertIsNone(summary["stopReason"])
            self.assertEqual(1, summary["pageNumberMismatch"])
            records = json.loads((project / "state/records.json").read_text(encoding="utf-8"))["records"]
            self.assertEqual("saved", records["1"]["status"])
            self.assertEqual(999, records["1"]["sourcePageNumber"])
            self.assertNotIn("observedPageId", records["1"])

    def test_accepted_source_exclusion_does_not_stop_crawl(self):
        with tempfile.TemporaryDirectory() as temp_name:
            project = Path(temp_name)
            (project / ".flow/local").mkdir(parents=True)
            (project / "configs").mkdir(parents=True, exist_ok=True)
            (project / "configs/wikiwiki-crawler.local.json").write_text(json.dumps({
                "userAgent": "test-agent",
                "acceptLanguage": "ja-JP",
                "cookie": "session=valid",
                "dailyLimit": 1,
                "delaySeconds": 0,
                "delayJitterSeconds": 0,
                "maxTransientRetries": 0,
                "maxRateLimitRetries": 0,
                "maxConsecutiveRateLimits": 1,
            }), encoding="utf-8")
            (project / "items.json").write_text(json.dumps([
                {"api_id": 337, "api_sortno": 337, "api_name": "烈風改二(一航戦/熟練)"},
            ]), encoding="utf-8")
            (project / "aliases.json").write_text(json.dumps({
                "schemaVersion": 1,
                "reviewStatus": "accepted",
                "aliases": [],
                "exclusions": [{
                    "id": "test",
                    "status": "accepted",
                    "start2Name": "烈風改二(一航戦/熟練)",
                    "reason": "Start2 internal equipment without a dedicated WikiWiki page.",
                }],
            }), encoding="utf-8")
            (project / "catalog.json").write_text(json.dumps({"kind": "equipment", "entries": []}), encoding="utf-8")

            args = argparse.Namespace(
                project=project,
                config=Path("configs/wikiwiki-crawler.local.json"),
                output=Path("state"),
                raw_root=Path("raw"),
                start2=Path("items.json"),
                name_aliases=Path("aliases.json"),
                catalog=Path("catalog.json"),
                equipment_ids=None,
                from_id=None,
                daily_limit=None,
                limit=None,
                refresh=False,
            )
            with mock.patch.object(crawler, "run_curl") as fetch:
                exit_code = crawler.crawl_command(args)

            self.assertEqual(exit_code, 0)
            fetch.assert_not_called()
            summary = json.loads((project / "state/summary.json").read_text(encoding="utf-8"))
            self.assertIsNone(summary["stopReason"])
            self.assertEqual(1, summary["sourceExcluded"])
            self.assertEqual(0, summary["remaining"])
            records = json.loads((project / "state/records.json").read_text(encoding="utf-8"))["records"]
            self.assertEqual("source-excluded", records["337"]["status"])

    def test_catalog_receipt_is_not_ready_before_detail_crawl(self):
        with tempfile.TemporaryDirectory() as temp_name:
            project = Path(temp_name)
            raw_root = project / "raw"
            catalog_dir = project / "catalog"
            for kind in ("ship", "equipment", "improvement"):
                raw = raw_root / f"{kind}.html"
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_text("<html>" + "x" * 300 + "</html>", encoding="utf-8")
                catalog_dir.mkdir(parents=True, exist_ok=True)
                (catalog_dir / f"{kind}-pages.json").write_text(json.dumps({
                    "kind": kind,
                    "rawCacheKey": raw.relative_to(raw_root).as_posix(),
                    "entries": [] if kind != "improvement" else [],
                }), encoding="utf-8")

            receipt = crawler.build_source_receipt(catalog_dir=catalog_dir, raw_root=raw_root, project=project)
            self.assertFalse(receipt["ready"])
            self.assertEqual("pending", receipt["details"]["equipment"]["status"])
            self.assertEqual("deferred", receipt["details"]["ship"]["status"])

    def test_detail_receipt_ready_requires_no_remaining_or_failed_pages(self):
        with tempfile.TemporaryDirectory() as temp_name:
            project = Path(temp_name)
            output = project / "state"
            raw_root = project / "raw"
            details = crawler._details_from_summary(
                summary={
                    "selected": 3,
                    "completed": 3,
                    "saved": 2,
                    "skipped": 1,
                    "sourceExcluded": 0,
                    "remaining": 0,
                    "failed": 0,
                    "stopReason": None,
                    "updatedAt": "2026-01-01T00:00:00+00:00",
                    "finishedAt": "2026-01-01T00:00:00+00:00",
                },
                output=output,
                raw_root=raw_root,
                project=project,
            )
            self.assertEqual("ready", details["equipment"]["status"])

            incomplete = crawler._details_from_summary(
                summary={"selected": 3, "completed": 2, "remaining": 1, "failed": 0, "stopReason": None},
                output=output,
                raw_root=raw_root,
                project=project,
            )
            self.assertEqual("incomplete", incomplete["equipment"]["status"])
            self.assertIn("remaining=1", incomplete["equipment"]["reason"])


if __name__ == "__main__":
    unittest.main()
