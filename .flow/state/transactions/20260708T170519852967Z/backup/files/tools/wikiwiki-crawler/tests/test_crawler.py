from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
TOOL = TOOL_DIR / "crawler.py"
MIGRATE = TOOL_DIR / "migrate_existing_html.py"
sys.path.insert(0, str(TOOL_DIR))

from page_catalog import load_name_aliases, normalize_name, parse_card_catalog, resolve_name  # noqa: E402
import crawler  # noqa: E402


class WikiWikiPageCatalogTest(unittest.TestCase):
    def test_name_match_uses_exact_list_url_and_normalizes_fullwidth_plus(self):
        source_url = "https://wikiwiki.jp/kancolle/%E8%A3%85%E5%82%99%E3%82%AB%E3%83%BC%E3%83%89%E4%B8%80%E8%A6%A7"
        html = """
        <html><body>
          <a href="/kancolle/8cm%E9%AB%98%E8%A7%92%E7%A0%B2%E6%94%B9%EF%BC%8B%E5%A2%97%E8%A8%AD%E6%A9%9F%E9%8A%83">
            <img alt="220:8cm高角砲改＋増設機銃">
          </a>
        </body></html>
        """
        catalog = parse_card_catalog(html, kind="equipment", source_url=source_url)
        result = resolve_name("8cm高角砲改+増設機銃", catalog)
        self.assertEqual(normalize_name("＋"), "+")
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["matchType"], "normalized-name")
        self.assertEqual(result["wikiName"], "8cm高角砲改＋増設機銃")
        self.assertIn("%EF%BC%8B", result["url"])
        self.assertEqual(result["urlSource"], "card-list-link")

    def test_exact_link_page_name_wins_over_truncated_card_label(self):
        source_url = "https://wikiwiki.jp/kancolle/%E8%A3%85%E5%82%99%E3%82%AB%E3%83%BC%E3%83%89%E4%B8%80%E8%A6%A7"
        html = '<a href="/kancolle/15.5cm%E4%B8%89%E9%80%A3%E8%A3%85%E7%A0%B2%28%E5%89%AF%E7%A0%B2%29"><img alt="012:15.5cm三連装砲(副砲"></a>'
        catalog = parse_card_catalog(html, kind="equipment", source_url=source_url)
        result = resolve_name("15.5cm三連装砲(副砲)", catalog)
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["wikiName"], "15.5cm三連装砲(副砲)")

    def test_human_accepted_name_alias_resolves_exact_wiki_page(self):
        source_url = "https://wikiwiki.jp/kancolle/%E8%A3%85%E5%82%99%E3%82%AB%E3%83%BC%E3%83%89%E4%B8%80%E8%A6%A7"
        html = '<a href="/kancolle/SK%E3%83%AC%E3%83%BC%E3%83%80%E3%83%BC"><img alt="278:SKレーダー"></a>'
        catalog = parse_card_catalog(html, kind="equipment", source_url=source_url)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "aliases.json"
            path.write_text(json.dumps({
                "schemaVersion": 1,
                "reviewStatus": "accepted",
                "aliases": [{
                    "id": "test",
                    "status": "accepted",
                    "start2Name": "SK レーダー",
                    "wikiName": "SKレーダー",
                }],
            }), encoding="utf-8")
            result = resolve_name("SK レーダー", catalog, aliases=load_name_aliases(path))
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["matchType"], "accepted-name-alias")
        self.assertEqual(result["wikiName"], "SKレーダー")

    def test_human_accepted_alias_can_resolve_direct_page_when_catalog_omits_entry(self):
        catalog = {"schemaVersion": 1, "kind": "equipment", "entries": []}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "aliases.json"
            path.write_text(json.dumps({
                "schemaVersion": 1,
                "reviewStatus": "accepted",
                "aliases": [{
                    "id": "test",
                    "status": "accepted",
                    "start2Name": "烈風改二戊型(一航戦/熟練)",
                    "wikiName": "烈風改二戊型(一航戦／熟練)",
                }],
            }), encoding="utf-8")
            result = resolve_name(
                "烈風改二戊型(一航戦/熟練)",
                catalog,
                aliases=load_name_aliases(path),
            )
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["matchType"], "accepted-name-alias-direct")
        self.assertEqual(result["wikiName"], "烈風改二戊型(一航戦／熟練)")
        self.assertIn("%EF%BC%8F", result["url"])

    def test_human_accepted_exclusion_is_not_resolved_or_requested(self):
        catalog = {"schemaVersion": 1, "kind": "equipment", "entries": []}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "aliases.json"
            path.write_text(json.dumps({
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
            result = resolve_name(
                "烈風改二(一航戦/熟練)",
                catalog,
                aliases=load_name_aliases(path),
            )
        self.assertEqual(result["status"], "excluded")
        self.assertEqual(result["matchType"], "accepted-name-exclusion")


    def test_match_report_counts_accepted_source_exclusions(self):
        catalog = {"schemaVersion": 1, "kind": "equipment", "entries": []}
        aliases = {"烈風改二(一航戦/熟練)": None}
        report = crawler.build_name_match_report(
            [{"equipmentId": 337, "equipmentName": "烈風改二(一航戦/熟練)"}],
            catalog,
            aliases,
        )

        self.assertEqual(report["counts"]["excluded"], 1)
        self.assertEqual(report["counts"]["invalid"], 0)
        self.assertEqual(report["matches"][0]["status"], "excluded")
        self.assertEqual(report["matches"][0]["matchType"], "accepted-name-exclusion")

    def test_match_report_converts_resolver_exceptions_to_invalid_diagnostics(self):
        report = crawler.build_name_match_report(
            [{"equipmentId": 1, "equipmentName": "Broken"}],
            {"schemaVersion": 1, "kind": "equipment", "entries": []},
            object(),
        )

        self.assertEqual(report["counts"]["invalid"], 1)
        self.assertEqual(report["matches"][0]["status"], "invalid")
        self.assertEqual(report["diagnostics"][0]["reason"], "resolver-exception")
        self.assertEqual(report["diagnostics"][0]["equipmentId"], 1)

    def test_duplicate_normalized_names_are_ambiguous(self):
        source_url = "https://wikiwiki.jp/kancolle/%E8%89%A6%E5%A8%98%E3%82%AB%E3%83%BC%E3%83%89%E4%B8%80%E8%A6%A7"
        html = """
        <a href="/kancolle/A"><img alt="001:A"></a>
        <a href="/kancolle/%EF%BC%A1"><img alt="002:Ａ"></a>
        """
        catalog = parse_card_catalog(html, kind="ship", source_url=source_url)
        result = resolve_name("Ⓐ", catalog)
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(len(result["candidates"]), 2)


class WikiWikiCrawlerToolTest(unittest.TestCase):
    def _write_config(self, root: Path, fake: Path) -> None:
        config = {
            "userAgent": "Mozilla/5.0 Test Browser",
            "acceptLanguage": "en",
            "cookie": "_cfuvid=test; __cf_bm=test",
            "delaySeconds": 0,
            "delayJitterSeconds": 0,
            "rateLimitCooldownSeconds": 0,
            "maxRateLimitRetries": 0,
            "maxConsecutiveRateLimits": 1,
            "transientRetrySeconds": 0,
            "maxTransientRetries": 0,
            "curlPath": str(fake),
        }
        (root / "configs").mkdir(parents=True, exist_ok=True)
        (root / "configs").mkdir(parents=True, exist_ok=True)
        (root / "configs/wikiwiki-crawler.local.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        (root / "configs").mkdir(parents=True, exist_ok=True)
        (root / "configs/wikiwiki-page-name-aliases.json").write_text(
            json.dumps({"schemaVersion": 1, "reviewStatus": "accepted", "aliases": []}),
            encoding="utf-8",
        )

    def test_catalog_inspect_and_capture_with_fake_curl(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data/start2_data").mkdir(parents=True)
            (root / "data/start2_data/api_mst_slotitem.json").write_text(
                json.dumps([
                    {"api_id": 1, "api_sortno": 1, "api_name": "Test One"},
                    {"api_id": 220, "api_sortno": 220, "api_name": "8cm高角砲改+増設機銃"},
                ]),
                encoding="utf-8",
            )
            fake = root / "fake-curl.py"
            fake.write_text(
                """#!/usr/bin/env python3
import pathlib, re, sys
conf = pathlib.Path(sys.argv[sys.argv.index('--config') + 1]).read_text()
out = re.search(r'^output = \"(.*)\"$', conf, re.M).group(1)
url = re.search(r'^url = \"(.*)\"$', conf, re.M).group(1)
if '%E8%A3%85%E5%82%99%E3%82%AB%E3%83%BC%E3%83%89%E4%B8%80%E8%A6%A7' in url:
    body = ('<html><body>'
            '<a href=\"/kancolle/Test%20One\"><img alt=\"001:Test One\"></a>'
            '<a href=\"/kancolle/8cm%E9%AB%98%E8%A7%92%E7%A0%B2%E6%94%B9%EF%BC%8B%E5%A2%97%E8%A8%AD%E6%A9%9F%E9%8A%83\"><img alt=\"220:8cm高角砲改＋増設機銃\"></a>'
            + ('x' * 400) + '</body></html>')
elif 'Test%20One' in url:
    body = '<html><body>No.001' + ('x' * 400) + '</body></html>'
elif '%EF%BC%8B' in url:
    body = '<html><body>No.220' + ('x' * 400) + '</body></html>'
else:
    body = '<html><body>unexpected URL ' + url + ('x' * 400) + '</body></html>'
pathlib.Path(out).write_text(body)
print('200', end='')
""",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            self._write_config(root, fake)

            catalog_run = subprocess.run(
                [sys.executable, str(TOOL), "--project", str(root), "catalog", "--kind", "equipment"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(catalog_run.returncode, 0, catalog_run.stderr + catalog_run.stdout)
            catalog_path = root / ".flow/local/wikiwiki-crawler/catalog/equipment-pages.json"
            catalog = json.loads(catalog_path.read_text())
            self.assertEqual(len(catalog["entries"]), 2)

            inspect = subprocess.run(
                [sys.executable, str(TOOL), "--project", str(root), "inspect"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(inspect.returncode, 0, inspect.stderr)
            self.assertIn("resolved=2", inspect.stdout)
            self.assertIn("unresolved=0", inspect.stdout)

            crawl = subprocess.run(
                [sys.executable, str(TOOL), "--project", str(root), "crawl"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(crawl.returncode, 0, crawl.stderr + crawl.stdout)
            summary = json.loads((root / ".flow/local/wikiwiki-crawler/summary.json").read_text())
            self.assertEqual(summary["saved"], 2)
            self.assertEqual(summary["urlResolved"], 2)
            self.assertEqual(summary["urlUnresolved"], 0)
            raw_root = root / ".flow/local/source-cache"
            self.assertTrue((raw_root / "wikiwiki.jp/kancolle/Test%20One.html").is_file())
            plus_path = raw_root / "wikiwiki.jp/kancolle/8cm%E9%AB%98%E8%A7%92%E7%A0%B2%E6%94%B9%EF%BC%8B%E5%A2%97%E8%A8%AD%E6%A9%9F%E9%8A%83.html"
            self.assertTrue(plus_path.is_file())
            records = json.loads((root / ".flow/local/wikiwiki-crawler/records.json").read_text())["records"]
            self.assertEqual(records["220"]["nameMatchType"], "normalized-name")
            self.assertEqual(records["220"]["wikiName"], "8cm高角砲改＋増設機銃")
            self.assertIn("%EF%BC%8B", records["220"]["url"])

    def test_catalog_all_writes_three_index_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data/start2_data").mkdir(parents=True)
            (root / "data/start2_data/api_mst_slotitem.json").write_text(
                json.dumps([{"api_id": 1, "api_sortno": 1, "api_name": "Test One"}]),
                encoding="utf-8",
            )
            fake = root / "fake-curl.py"
            fake.write_text(
                """#!/usr/bin/env python3
import pathlib, re, sys
conf = pathlib.Path(sys.argv[sys.argv.index('--config') + 1]).read_text()
out = re.search(r'^output = \"(.*)\"$', conf, re.M).group(1)
url = re.search(r'^url = \"(.*)\"$', conf, re.M).group(1)
if '%E8%A3%85%E5%82%99%E3%82%AB%E3%83%BC%E3%83%89%E4%B8%80%E8%A6%A7' in url:
    body = '<html><body><a href=\"/kancolle/Test%20One\"><img alt=\"001:Test One\"></a>' + ('x' * 400) + '</body></html>'
elif '%E8%89%A6%E5%A8%98%E3%82%AB%E3%83%BC%E3%83%89%E4%B8%80%E8%A6%A7' in url:
    body = '<html><body><a href=\"/kancolle/Ship%20One\"><img alt=\"001:Ship One\"></a>' + ('x' * 400) + '</body></html>'
elif '%E6%94%B9%E4%BF%AE%E8%A1%A8' in url:
    body = '<html><body><table><tr><td>改修</td></tr></table>' + ('x' * 400) + '</body></html>'
else:
    body = '<html><body>unexpected URL ' + url + ('x' * 400) + '</body></html>'
pathlib.Path(out).write_text(body)
print('200', end='')
""",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            self._write_config(root, fake)

            completed = subprocess.run(
                [sys.executable, str(TOOL), "--project", str(root), "catalog", "--kind", "all"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            catalog_dir = root / ".flow/local/wikiwiki-crawler/catalog"
            receipt = json.loads((root / ".flow/local/wikiwiki-crawler/source-receipt.json").read_text())
            self.assertFalse(receipt["ready"])
            self.assertEqual(receipt["details"]["equipment"]["status"], "pending")
            self.assertEqual(receipt["requiredIndexes"], ["ship", "equipment", "improvement"])
            self.assertEqual(receipt["indexes"]["ship"]["role"], "locator-index")
            self.assertEqual(receipt["indexes"]["equipment"]["role"], "locator-index")
            self.assertEqual(receipt["indexes"]["improvement"]["role"], "validation-index")
            self.assertTrue((catalog_dir / "ship-pages.json").is_file())
            self.assertTrue((catalog_dir / "equipment-pages.json").is_file())
            improvement = json.loads((catalog_dir / "improvement-pages.json").read_text())
            self.assertEqual(improvement["joinKey"], "none-validation-only")
            self.assertTrue(improvement["diagnostics"]["validationOnly"])

    def test_unresolved_name_is_not_requested(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data/start2_data").mkdir(parents=True)
            (root / "data/start2_data/api_mst_slotitem.json").write_text(
                json.dumps([{"api_id": 1, "api_sortno": 1, "api_name": "Missing Name"}]),
                encoding="utf-8",
            )
            marker = root / "curl-called"
            fake = root / "fake-curl.py"
            fake.write_text(
                f"#!/usr/bin/env python3\nfrom pathlib import Path\nPath({str(marker)!r}).write_text('called')\nprint('500', end='')\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            self._write_config(root, fake)
            catalog_dir = root / ".flow/local/wikiwiki-crawler/catalog"
            catalog_dir.mkdir(parents=True)
            (catalog_dir / "equipment-pages.json").write_text(
                json.dumps({
                    "schemaVersion": 1,
                    "kind": "equipment",
                    "entries": [{
                        "wikiName": "Other Name",
                        "normalizedName": "Other Name",
                        "url": "https://wikiwiki.jp/kancolle/Other%20Name",
                        "urlSource": "card-list-link",
                    }],
                }),
                encoding="utf-8",
            )
            crawl = subprocess.run(
                [sys.executable, str(TOOL), "--project", str(root), "crawl"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(crawl.returncode, 75, crawl.stderr + crawl.stdout)
            self.assertFalse(marker.exists())
            records = json.loads((root / ".flow/local/wikiwiki-crawler/records.json").read_text())["records"]
            self.assertEqual(records["1"]["status"], "url-unresolved")

    def test_migrate_existing_html_into_shared_raw_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / ".flow/local/wikiwiki-crawler"
            (source / "raw").mkdir(parents=True)
            html = "<html><body>No.003" + ("x" * 400) + "</body></html>"
            source_html = source / "raw/3.html"
            source_html.write_text(html, encoding="utf-8")
            digest = hashlib.sha256(source_html.read_bytes()).hexdigest()
            (source / "records.json").write_text(
                json.dumps({
                    "schemaVersion": 1,
                    "records": {
                        "3": {
                            "equipmentId": 3,
                            "equipmentName": "10cm連装高角砲",
                            "status": "saved",
                            "httpCode": 200,
                            "fetchedAt": "2026-07-05T06:21:59+00:00",
                            "url": "https://wikiwiki.jp/kancolle/10cm%E9%80%A3%E8%A3%85%E9%AB%98%E8%A7%92%E7%A0%B2",
                            "rawPath": ".flow/local/wikiwiki-crawler/raw/3.html",
                            "sha256": digest,
                        }
                    },
                }),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(MIGRATE), "--project", str(root)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            target = root / ".flow/local/source-cache/wikiwiki.jp/kancolle/10cm%E9%80%A3%E8%A3%85%E9%AB%98%E8%A7%92%E7%A0%B2.html"
            self.assertTrue(target.is_file())
            self.assertTrue(source_html.is_file())
            records = json.loads((source / "records.json").read_text())["records"]
            self.assertEqual(
                records["3"]["rawPath"],
                ".flow/local/source-cache/wikiwiki.jp/kancolle/10cm%E9%80%A3%E8%A3%85%E9%AB%98%E8%A7%92%E7%A0%B2.html",
            )
            self.assertTrue((source / "migration-summary.json").is_file())


if __name__ == "__main__":
    unittest.main()
