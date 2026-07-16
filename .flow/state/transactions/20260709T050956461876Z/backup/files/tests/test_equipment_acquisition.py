from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from service.data_package.acquisition_references import (
    QuestReferenceCatalog,
    ShipReferenceCatalog,
    resolve_record_references,
)
from service.data_package.equipment_acquisition import (
    build_page_name_candidates,
    classify_method_types,
    parse_equipment_acquisition_page,
    parse_equipment_catalog_page,
)
from service.data_package.equipment_acquisition_crawl import run_full_crawl
from service.data_package.equipment_acquisition_raw_parse import run_offline_parse
from util.start2.start2_ship_utils import Start2ShipUtils, ship_utils


def _page(body: str, *, no: int = 3, development: str = "開発可") -> str:
    return f"""
    <html><body>
      <div>No.{no:03d}</div>
      <table><tr><th>備考</th><td>{development}、改修可、入手方法</td></tr></table>
      <h2>ゲームにおいて</h2>
      <p>説明</p>
      <h3 id="acquisition">入手方法について</h3>
      {body}
      <h3>改修工廠について</h3>
      <p>ここは取得対象外</p>
    </body></html>
    """


def _catalog(*entries: tuple[int, str]) -> str:
    cards = "".join(
        f'<a href="/kancolle/{name}"><img alt="{equipment_id:03d}:{name}" src="weapon{equipment_id:03d}.png"></a>'
        for equipment_id, name in entries
    )
    return f"<html><body><h1>装備カード一覧</h1>{cards}</body></html>"


class EquipmentAcquisitionTest(unittest.TestCase):
    def test_page_name_candidates_support_wikiwiki_full_width_plus(self):
        self.assertEqual(
            build_page_name_candidates("10cm連装高角砲改+高射装置改"),
            ["10cm連装高角砲改+高射装置改", "10cm連装高角砲改＋高射装置改"],
        )

    def test_catalog_parser_uses_image_id_and_page_link(self):
        entries, issues = parse_equipment_catalog_page(
            _catalog((3, "10cm連装高角砲"), (161, "16inch三連装砲 Mk.7"))
        )
        self.assertEqual(issues, [])
        self.assertEqual([entry.equipment_id for entry in entries], [3, 161])
        self.assertEqual(entries[1].page_name, "16inch三連装砲 Mk.7")
        self.assertTrue(entries[1].source_url.endswith("/16inch三連装砲 Mk.7"))

    def test_classify_method_types_keeps_multi_source_summary(self):
        self.assertEqual(
            classify_method_types("ランキング報酬、イベント海域報酬、Iowa改の初期装備"),
            ["ship", "ranking", "event"],
        )


    def test_generic_update_wording_is_classified_as_improvement(self):
        self.assertEqual(
            classify_method_types("九五式爆雷からの更新で入手可能"),
            ["improvement"],
        )

    def test_summary_table_exact_improvement_value_is_acquisition(self):
        html = """
        <html><body>
          <div>No.327</div>
          <h3>ゲームにおいて</h3>
          <table>
            <tr><th>装備</th><th>入手方法</th></tr>
            <tr><td>S-51J改</td><td>改修</td></tr>
          </table>
        </body></html>
        """
        record, issues = parse_equipment_acquisition_page(
            html,
            equipment_id=327,
            equipment_name="S-51J改",
            source_url="https://wikiwiki.jp/kancolle/S-51J改",
        )
        self.assertEqual([issue.kind for issue in issues], ["missing-acquisition-section"])
        self.assertEqual(record["coverageStatus"], "fallback")
        self.assertEqual(record["methods"][0]["types"], ["improvement"])

    def test_fallback_discovers_nested_high_signal_list(self):
        html = """
        <html><body>
          <div>No.155</div>
          <h3>ゲームにおいて</h3>
          <ul><li>実装経緯
            <ul><li>任務「艦戦隊の再編成」報酬として入手できる。</li></ul>
          </li></ul>
        </body></html>
        """
        record, issues = parse_equipment_acquisition_page(
            html,
            equipment_id=155,
            equipment_name="零戦21型(付岩本小隊)",
            source_url="https://wikiwiki.jp/kancolle/test-155",
        )
        self.assertEqual([issue.kind for issue in issues], ["missing-acquisition-section"])
        self.assertEqual(record["coverageStatus"], "fallback")
        self.assertEqual(len(record["methods"]), 1)
        self.assertEqual(record["currentMethodTypes"], ["quest"])

    def test_quest_reward_link_is_high_confidence_context(self):
        html = _page("""
          <ul><li>2020年『改装護衛駆逐艦「Fletcher Mk.II」作戦開始！』確定報酬
            <a href="/kancolle/任務#id-B149">任務</a>
          </li></ul>
        """, no=377)
        record, issues = parse_equipment_acquisition_page(
            html,
            equipment_id=377,
            equipment_name="RUR-4A Weapon Alpha改",
            source_url="https://wikiwiki.jp/kancolle/test-377",
        )
        self.assertEqual(issues, [])
        self.assertEqual(record["methods"][0]["types"], ["quest"])

    def test_event_reward_table_header_is_dictionary_context(self):
        html = _page("""
          <p>過去の入手方法</p>
          <table>
            <tr><th>海域</th><th>難易度</th><th>入手数</th></tr>
            <tr><td>E1</td><td>甲</td><td>×2</td></tr>
            <tr><td>E2</td><td>甲・乙</td><td>×1</td></tr>
          </table>
        """, no=477)
        record, issues = parse_equipment_acquisition_page(
            html,
            equipment_id=477,
            equipment_name="熟練甲板要員",
            source_url="https://wikiwiki.jp/kancolle/test-477",
        )
        self.assertEqual(issues, [])
        self.assertEqual(len(record["methods"]), 2)
        self.assertTrue(all(method["types"] == ["event"] for method in record["methods"]))

    def test_parse_development_and_ship_table_sources(self):
        html = _page("""
          <ul class="list1">
            <li><a href="/kancolle/開発">開発</a>可能。</li>
            <li>初期装備艦は下表の通り。</li>
          </ul>
          <table>
            <tr><th>Lv</th><th>駆逐艦</th><th>備考</th></tr>
            <tr><td>20</td><td><a href="/kancolle/朝潮改">朝潮改</a>、大潮改</td><td></td></tr>
            <tr><td>67</td><td><a href="/kancolle/浜風乙改">浜風乙改</a></td><td>第二改造</td></tr>
          </table>
        """)
        record, issues = parse_equipment_acquisition_page(
            html,
            equipment_id=3,
            equipment_name="10cm連装高角砲",
            source_url="https://wikiwiki.jp/kancolle/test",
        )
        self.assertEqual(issues, [])
        self.assertEqual(record["pageEquipmentId"], 3)
        self.assertIs(record["developmentAvailable"], True)
        self.assertEqual(record["currentMethodTypes"], ["development", "ship"])
        table_methods = [m for m in record["methods"] if m["evidenceKind"] == "table-row"]
        self.assertEqual(len(table_methods), 2)
        self.assertEqual(table_methods[0]["types"], ["ship"])
        self.assertIn("朝潮改", table_methods[0]["rawText"])
        self.assertEqual(table_methods[0]["links"][0]["text"], "朝潮改")

    def test_parse_current_and_historical_sources_separately(self):
        html = _page("""
          <ul class="list1">
            <li>「10cm連装高角砲改 ★max」からの改修更新</li>
            <li>任務『防空駆逐艦、参戦！』報酬</li>
          </ul>
          <p>過去の入手方法</p>
          <div><ul class="list1"><li>2025年秋刀魚祭りイベント報酬</li></ul></div>
        """, no=533, development="開発不可")
        record, issues = parse_equipment_acquisition_page(
            html,
            equipment_id=533,
            equipment_name="10cm連装高角砲改+高射装置改",
            source_url="https://wikiwiki.jp/kancolle/test-533",
        )
        self.assertEqual(issues, [])
        self.assertIs(record["developmentAvailable"], False)
        self.assertEqual(record["currentMethodTypes"], ["improvement", "quest"])
        self.assertEqual(record["historicalMethodTypes"], ["event"])
        self.assertEqual(record["methods"][-1]["availability"], "historical")

    def test_custom_acquisition_heading_and_quest_context_are_supported(self):
        html = _page("""
          <h3>ドラム缶の入手方法</h3>
          <ul class="list1">
            <li>任務報酬：以下の任務で入手可能。
              <ul>
                <li>『輸送用ドラム缶の準備』(1回のみ:3個)</li>
                <li>『南西諸島方面「海上警備行動」発令！』(選択報酬)</li>
              </ul>
            </li>
          </ul>
        """).replace('<h3 id="acquisition">入手方法について</h3>', '')
        record, issues = parse_equipment_acquisition_page(
            html,
            equipment_id=3,
            equipment_name="ドラム缶(輸送用)",
            source_url="https://wikiwiki.jp/kancolle/test-drum",
        )
        self.assertEqual(issues, [])
        self.assertEqual(len(record["methods"]), 2)
        self.assertTrue(all("quest" in method["types"] for method in record["methods"]))
        self.assertIn("発令！』", record["methods"][1]["rawText"])

    def test_dated_current_reward_is_not_implicitly_historical(self):
        html = _page("""
          <ul><li>2024年 鎮守府秋刀魚祭り任務の選択報酬</li></ul>
        """)
        record, issues = parse_equipment_acquisition_page(
            html,
            equipment_id=3,
            equipment_name="test",
            source_url="https://wikiwiki.jp/kancolle/test-current-date",
        )
        self.assertEqual(issues, [])
        self.assertEqual(record["methods"][0]["availability"], "current-or-summary")
        self.assertEqual(record["historicalMethodTypes"], [])

    def test_nested_event_table_inherits_event_context(self):
        html = _page("""
          <ul>
            <li>イベント海域 突破報酬
              <table>
                <tr><th>年次</th><th>海域</th></tr>
                <tr><td>2024春</td><td>E-2甲</td></tr>
              </table>
            </li>
          </ul>
        """)
        record, issues = parse_equipment_acquisition_page(
            html,
            equipment_id=3,
            equipment_name="test",
            source_url="https://wikiwiki.jp/kancolle/test-event-table",
        )
        self.assertEqual(issues, [])
        table_method = next(m for m in record["methods"] if m["evidenceKind"] == "table-row")
        self.assertEqual(table_method["types"], ["event"])

    def test_summary_table_fallback_does_not_capture_unrelated_prose(self):
        html = """
        <html><body>
          <div>No.003</div>
          <table>
            <tr><th>装備</th><th>入手方法</th></tr>
            <tr><td>test</td><td>初期装備、イベント</td></tr>
          </table>
          <h2>ゲームにおいて</h2>
          <ul><li>性能比較や運用についての一般的な説明。</li></ul>
        </body></html>
        """
        record, issues = parse_equipment_acquisition_page(
            html,
            equipment_id=3,
            equipment_name="test",
            source_url="https://wikiwiki.jp/kancolle/test-summary-fallback",
        )
        self.assertEqual([issue.kind for issue in issues], ["missing-acquisition-section"])
        self.assertEqual(len(record["methods"]), 1)
        self.assertEqual(record["methods"][0]["types"], ["ship", "event"])

    def test_mixed_historical_summary_is_split_from_current_nested_fact(self):
        html = _page("""
          <ul class="list1">
            <li>これまでの入手方法はランキング報酬、イベント海域クリア報酬、Iowa改の初期装備。
              <ul><li>現在は大型艦建造でIowaが建造可能。</li></ul>
            </li>
          </ul>
        """, no=161, development="開発不可")
        record, issues = parse_equipment_acquisition_page(
            html,
            equipment_id=161,
            equipment_name="16inch三連装砲 Mk.7",
            source_url="https://wikiwiki.jp/kancolle/test-161",
        )
        self.assertEqual(issues, [])
        historical = [m for m in record["methods"] if m["availability"] == "historical"]
        current = [m for m in record["methods"] if m["availability"] == "current"]
        self.assertEqual(historical[0]["types"], ["ship", "ranking", "event"])
        self.assertEqual(current[0]["types"], ["construction"])

    def test_page_without_acquisition_section_uses_low_confidence_fallback(self):
        html = """
        <html><body>
          <div>No.278</div>
          <table><tr><td>開発不可、入手方法</td></tr></table>
          <h2>ゲームにおいて</h2>
          <ul>
            <li>2018年イベント海域突破報酬として実装された。</li>
            <li>現在はGambier Bay Mk.IIの初期装備とイヤーリー任務報酬で入手可能。</li>
          </ul>
          <h3>装備の運用方法について</h3>
          <p>比較表ではイベントや任務という語が出るが取得対象外。</p>
        </body></html>
        """
        record, issues = parse_equipment_acquisition_page(
            html,
            equipment_id=278,
            equipment_name="SKレーダー",
            source_url="https://wikiwiki.jp/kancolle/SKレーダー",
        )
        self.assertEqual([issue.kind for issue in issues], ["missing-acquisition-section"])
        self.assertEqual(record["evidenceScope"], "page-fallback")
        self.assertEqual(record["coverageStatus"], "fallback")
        self.assertEqual(record["historicalMethodTypes"], ["event"])
        self.assertEqual(record["currentMethodTypes"], ["quest", "ship"])
        self.assertEqual(len(record["methods"]), 2)

    def test_page_id_matches_when_japanese_text_is_adjacent(self):
        html = "<html><body><div>No.003</div><div>装備名</div><h3>入手方法</h3><ul><li>開発可能。</li></ul></body></html>"
        record, issues = parse_equipment_acquisition_page(
            html,
            equipment_id=3,
            equipment_name="10cm連装高角砲",
            source_url="https://wikiwiki.jp/kancolle/test",
        )
        self.assertEqual(issues, [])
        self.assertEqual(record["pageEquipmentId"], 3)
        self.assertIs(record["accepted"], True)

    def test_id_mismatch_is_reported_and_record_rejected(self):
        record, issues = parse_equipment_acquisition_page(
            _page("<ul><li>任務報酬</li></ul>", no=999),
            equipment_id=3,
            equipment_name="10cm連装高角砲",
            source_url="https://wikiwiki.jp/kancolle/wrong",
        )
        self.assertEqual(record["issueCount"], 1)
        self.assertIs(record["accepted"], False)
        self.assertEqual(record["coverageStatus"], "rejected")
        self.assertEqual(issues[0].kind, "equipment-id-mismatch")


    def test_ship_and_quest_references_resolve_to_stable_ids(self):
        html = _page("""
          <ul class="list1">
            <li>任務『防空駆逐艦、参戦！』報酬</li>
            <li>初期装備艦は下表の通り。</li>
          </ul>
          <table>
            <tr><th>Lv</th><th>駆逐艦</th></tr>
            <tr><td>20</td><td><a href="/kancolle/朝潮改">朝潮改</a>、大潮改</td></tr>
            <tr><td>67</td><td><a href="/kancolle/浜風乙改">浜風乙改</a></td></tr>
          </table>
        """)
        record, parse_issues = parse_equipment_acquisition_page(
            html,
            equipment_id=3,
            equipment_name="10cm連装高角砲",
            source_url="https://wikiwiki.jp/kancolle/test",
        )
        quests = QuestReferenceCatalog([
            {
                "questKey": 1234,
                "code": "F123",
                "name": "防空駆逐艦、参戦！",
            }
        ])
        reference_issues = resolve_record_references(
            record,
            ships=ShipReferenceCatalog.load(),
            quests=quests,
        )
        self.assertEqual(parse_issues, [])
        self.assertEqual(reference_issues, [])
        self.assertEqual(record["resolvedShipIds"], [248, 249, 558])
        self.assertEqual(record["resolvedQuestKeys"], [1234])
        self.assertEqual(record["schemaVersion"], 3)
        quest_method = next(
            method for method in record["methods"] if "quest" in method["types"]
        )
        self.assertEqual(quest_method["questReferences"][0]["questCode"], "F123")
        self.assertEqual(quest_method["questReferences"][0]["status"], "resolved")

    def test_quest_reference_requires_complete_exact_name(self):
        catalog = QuestReferenceCatalog([
            {
                "questKey": 1234,
                "code": "F123",
                "name": "防空駆逐艦、参戦！",
            }
        ])
        self.assertEqual(
            catalog.resolve_name("防空駆逐艦", evidence="test")["status"],
            "unresolved",
        )
        self.assertEqual(catalog.scan_text("任務『防空駆逐艦』報酬", evidence="test"), [])

    def test_nested_quotes_match_full_canonical_quest_name(self):
        catalog = QuestReferenceCatalog([
            {
                "questKey": 987,
                "code": "B193",
                "name": "「Gotland」戦隊、進撃せよ！",
            },
            {
                "questKey": 988,
                "code": "B194",
                "name": "改装航空軽巡「Gotland andra」、出撃！",
            },
        ])
        refs = catalog.scan_text(
            "任務「「Gotland」戦隊、進撃せよ！」の選択報酬",
            evidence="method-text",
        )
        self.assertEqual([ref["questKey"] for ref in refs], [987])
        self.assertEqual(refs[0]["status"], "resolved")
        self.assertEqual(refs[0]["evidence"], "method-text:exact-name")

    def test_ship_reference_catalog_excludes_non_player_start2_records(self):
        catalog = ShipReferenceCatalog(
            Start2ShipUtils([
                {"api_id": 1, "api_sortno": 1, "api_name": "玩家艦"},
                {"api_id": 1501, "api_sortno": 0, "api_name": "深海艦"},
            ]),
            kcwiki_ship_path=None,
        )
        self.assertEqual(
            catalog.resolve_exact("玩家艦", evidence="test")["shipId"],
            1,
        )
        self.assertEqual(
            catalog.resolve_exact("深海艦", evidence="test")["status"],
            "unresolved",
        )

    def test_kcwiki_suffix_disambiguates_duplicate_start2_ship_name(self):
        record = {
            "equipmentId": 175,
            "equipmentName": "雷電",
            "sourceUrl": "https://wikiwiki.jp/kancolle/雷電",
            "methods": [
                {
                    "types": ["ship"],
                    "rawText": "宗谷(特務艦)の初期装備",
                    "links": [],
                    "evidenceKind": "list-item",
                }
            ],
        }
        issues = resolve_record_references(
            record,
            ships=ShipReferenceCatalog.load(),
            quests=QuestReferenceCatalog.empty(),
        )
        self.assertEqual(issues, [])
        self.assertEqual(record["resolvedShipIds"], [699])


    def test_ambiguous_ship_explicit_forms_resolve_directly(self):
        catalog = ShipReferenceCatalog(
            Start2ShipUtils([
                {"api_id": 1022, "api_sortno": 1022, "api_name": "Glorious"},
                {"api_id": 1027, "api_sortno": 1027, "api_name": "Glorious"},
            ]),
            kcwiki_ship_path=None,
        )
        battlecruiser = catalog.resolve_exact(
            "Glorious(巡洋戦艦)", evidence="method-text"
        )
        carrier = catalog.resolve_exact(
            "Glorious(正規空母)", evidence="method-text"
        )
        carrier_synonym = catalog.resolve_exact(
            "Glorious(航空母艦)", evidence="method-text"
        )
        self.assertEqual(battlecruiser["shipId"], 1022)
        self.assertEqual(carrier["shipId"], 1027)
        self.assertEqual(carrier_synonym["shipId"], 1027)
        self.assertEqual(
            battlecruiser["resolution"], "ambiguous-ship-explicit-name"
        )

    def test_link_target_can_refine_visible_base_ship_name(self):
        catalog = ShipReferenceCatalog(
            Start2ShipUtils([
                {"api_id": 106, "api_sortno": 106, "api_name": "翔鶴"},
                {"api_id": 288, "api_sortno": 288, "api_name": "翔鶴改"},
            ]),
            kcwiki_ship_path=None,
        )
        record = {
            "equipmentId": 21,
            "equipmentName": "零式艦戦52型",
            "sourceUrl": "https://wikiwiki.jp/kancolle/零式艦戦52型",
            "methods": [{
                "types": ["ship"],
                "rawText": "翔鶴の初期装備",
                "links": [{
                    "text": "翔鶴",
                    "href": "https://wikiwiki.jp/kancolle/翔鶴改",
                }],
            }],
        }
        issues = resolve_record_references(
            record, ships=catalog, quests=QuestReferenceCatalog.empty()
        )
        self.assertEqual(issues, [])
        self.assertEqual(record["resolvedShipIds"], [288])
        reference = record["methods"][0]["shipReferences"][0]
        self.assertEqual(reference["resolution"], "link-target-more-specific")
        self.assertEqual(reference["evidence"], "link-target-authoritative")
        self.assertEqual(reference["linkTextShipId"], 106)
        self.assertEqual(reference["canonicalShipId"], 288)
        self.assertEqual(reference["start2Ship"]["shipId"], 288)
        cross_validation = reference["shipPageCrossValidation"]
        self.assertEqual(cross_validation["status"], "accepted")
        self.assertEqual(cross_validation["selectedShip"]["shipId"], 288)
        self.assertEqual(cross_validation["linkTextReference"]["canonicalShipId"], 106)
        self.assertEqual(cross_validation["linkPageReference"]["canonicalShipId"], 288)

    def test_unrelated_link_target_conflict_still_stops(self):
        catalog = ShipReferenceCatalog(
            Start2ShipUtils([
                {"api_id": 1, "api_sortno": 1, "api_name": "赤城"},
                {"api_id": 2, "api_sortno": 2, "api_name": "加賀"},
            ]),
            kcwiki_ship_path=None,
        )
        record = {
            "equipmentId": 999,
            "equipmentName": "test",
            "sourceUrl": "https://wikiwiki.jp/kancolle/test",
            "methods": [{
                "types": ["ship"],
                "rawText": "赤城の初期装備",
                "links": [{
                    "text": "赤城",
                    "href": "https://wikiwiki.jp/kancolle/加賀",
                }],
            }],
        }
        issues = resolve_record_references(
            record, ships=catalog, quests=QuestReferenceCatalog.empty()
        )
        self.assertEqual([issue["kind"] for issue in issues], [
            "ship-reference-ambiguous"
        ])
        reference = issues[0]["reference"]
        self.assertEqual(reference["evidence"], "link-target-conflict")
        self.assertEqual(reference["candidateShips"], [
            {"shipId": 1, "shipName": "赤城", "apiSortno": 1},
            {"shipId": 2, "shipName": "加賀", "apiSortno": 2},
        ])
        cross_validation = reference["shipPageCrossValidation"]
        self.assertEqual(cross_validation["status"], "rejected")
        self.assertEqual(cross_validation["candidateShips"], [
            {"shipId": 1, "shipName": "赤城", "apiSortno": 1},
            {"shipId": 2, "shipName": "加賀", "apiSortno": 2},
        ])

    def test_souya_unqualified_link_target_is_special_purpose_form(self):
        catalog = ShipReferenceCatalog(
            Start2ShipUtils([
                {"api_id": 699, "api_sortno": 699, "api_name": "宗谷"},
                {"api_id": 700, "api_sortno": 700, "api_name": "宗谷"},
            ]),
            kcwiki_ship_path=None,
        )
        record = {
            "equipmentId": 49,
            "equipmentName": "25mm単装機銃",
            "sourceUrl": "https://wikiwiki.jp/kancolle/25mm単装機銃",
            "methods": [{
                "types": ["ship"],
                "rawText": "宗谷の初期装備",
                "links": [{
                    "text": "宗谷",
                    "href": "https://wikiwiki.jp/kancolle/宗谷",
                }],
            }],
        }
        issues = resolve_record_references(
            record, ships=catalog, quests=QuestReferenceCatalog.empty()
        )
        self.assertEqual(issues, [])
        self.assertEqual(record["resolvedShipIds"], [699])
        reference = record["methods"][0]["shipReferences"][0]
        self.assertEqual(reference["resolution"], "ambiguous-ship-link-target")
        self.assertEqual(reference["explicitShipName"], "宗谷(特務艦)")
        self.assertEqual(reference["canonicalShipId"], 699)
        self.assertEqual(reference["shipPageCrossValidation"]["status"], "accepted")
        self.assertEqual(reference["shipPageCrossValidation"]["selectedShip"]["shipId"], 699)

    def test_bare_ambiguous_ship_requires_link_target_cross_validation(self):
        catalog = ShipReferenceCatalog(
            Start2ShipUtils([
                {"api_id": 1022, "api_sortno": 1022, "api_name": "Glorious"},
                {"api_id": 1027, "api_sortno": 1027, "api_name": "Glorious"},
            ]),
            kcwiki_ship_path=None,
        )
        record = {
            "equipmentId": 566,
            "equipmentName": "10.2cm三連装副砲",
            "sourceUrl": "https://wikiwiki.jp/kancolle/10.2cm三連装副砲",
            "methods": [{
                "types": ["ship"],
                "rawText": "Gloriousの初期装備",
                "links": [{
                    "text": "Glorious",
                    "href": "https://wikiwiki.jp/kancolle/Glorious",
                }],
            }],
        }
        issues = resolve_record_references(
            record, ships=catalog, quests=QuestReferenceCatalog.empty()
        )
        self.assertEqual(issues, [])
        self.assertEqual(record["resolvedShipIds"], [1022])
        reference = record["methods"][0]["shipReferences"][0]
        self.assertEqual(reference["resolution"], "ambiguous-ship-link-target")
        self.assertEqual(reference["linkTarget"], "Glorious")

    def test_actual_carrier_page_name_resolves_directly(self):
        catalog = ShipReferenceCatalog(
            Start2ShipUtils([
                {"api_id": 1022, "api_sortno": 1022, "api_name": "Glorious"},
                {"api_id": 1027, "api_sortno": 1027, "api_name": "Glorious"},
            ]),
            kcwiki_ship_path=None,
        )
        record = {
            "equipmentId": 567,
            "equipmentName": "Sea Gladiator",
            "sourceUrl": "https://wikiwiki.jp/kancolle/Sea Gladiator",
            "methods": [{
                "types": ["ship"],
                "rawText": "初期装備艦：Glorious(正規空母)",
                "links": [{
                    "text": "Glorious(正規空母)",
                    "href": "https://wikiwiki.jp/kancolle/Glorious(正規空母)",
                }],
            }],
        }
        issues = resolve_record_references(
            record, ships=catalog, quests=QuestReferenceCatalog.empty()
        )
        self.assertEqual(issues, [])
        self.assertEqual(record["resolvedShipIds"], [1027])

    def test_bare_ambiguous_ship_without_known_link_target_stops(self):
        catalog = ShipReferenceCatalog(
            Start2ShipUtils([
                {"api_id": 1022, "api_sortno": 1022, "api_name": "Glorious"},
                {"api_id": 1027, "api_sortno": 1027, "api_name": "Glorious"},
            ]),
            kcwiki_ship_path=None,
        )
        record = {
            "equipmentId": 567,
            "equipmentName": "Sea Gladiator",
            "sourceUrl": "https://wikiwiki.jp/kancolle/Sea Gladiator",
            "methods": [{
                "types": ["ship"],
                "rawText": "Gloriousの初期装備",
                "links": [{
                    "text": "Glorious",
                    "href": "https://wikiwiki.jp/kancolle/Glorious(未確定)",
                }],
            }],
        }
        issues = resolve_record_references(
            record, ships=catalog, quests=QuestReferenceCatalog.empty()
        )
        self.assertEqual([issue["kind"] for issue in issues], [
            "ship-reference-ambiguous"
        ])
        reference = issues[0]["reference"]
        self.assertEqual(reference["candidateShipIds"], [1022, 1027])
        self.assertEqual(reference["candidateShipNames"], [
            "Glorious(巡洋戦艦)",
            "Glorious(正規空母)",
        ])
        self.assertEqual(reference["evidence"], "link-cross-validation-failed")

    def test_generic_ship_prose_is_not_reported_as_unresolved_reference(self):
        record = {
            "equipmentId": 999,
            "equipmentName": "test",
            "sourceUrl": "https://wikiwiki.jp/kancolle/test",
            "methods": [
                {
                    "types": ["ship", "quest"],
                    "rawText": "多くの空母が初期装備。任務『存在しない任務』報酬",
                    "links": [],
                    "evidenceKind": "list-item",
                }
            ],
        }
        issues = resolve_record_references(
            record,
            ships=ShipReferenceCatalog.load(),
            quests=QuestReferenceCatalog([
                {"questKey": 1, "code": "A01", "name": "別の任務"}
            ]),
        )
        self.assertEqual(
            [issue["kind"] for issue in issues],
            ["quest-reference-unresolved"],
        )
        self.assertNotIn("shipReferences", record["methods"][0])

    def test_full_crawl_exports_all_diagnostic_files(self):
        catalog_html = _catalog((3, "10cm連装高角砲"))
        page_html = _page("<ul><li>開発可能。</li><li>任務報酬</li></ul>", no=3)

        quest_catalog = """{"1234":{"code":"F123","name":"防空駆逐艦、参戦！"}}"""

        def fake_fetch(url: str) -> str:
            if "kcQuests" in url:
                return quest_catalog
            if "装備カード一覧" in url or "%E8%A3%85%E5%82%99" in url:
                return catalog_html
            if url.endswith("/10cm%E9%80%A3%E8%A3%85%E9%AB%98%E8%A7%92%E7%A0%B2") or url.endswith("/10cm連装高角砲"):
                return page_html
            raise RuntimeError(url)

        with tempfile.TemporaryDirectory() as temp_name:
            output = Path(temp_name)
            with mock.patch(
                "service.data_package.equipment_acquisition_crawl.player_equipment_items",
                return_value=[{"api_id": 3, "api_sortno": 3, "api_name": "10cm連装高角砲"}],
            ):
                metadata = run_full_crawl(
                    output_dir=output,
                    delay_seconds=0,
                    fetch_text=fake_fetch,
                )
            self.assertEqual(metadata["mode"], "full-diagnostic-crawl")
            self.assertEqual(metadata["selectedEquipmentCount"], 1)
            self.assertEqual(metadata["recordCount"], 1)
            self.assertIs(metadata["canonicalDataChanged"], False)
            self.assertIs(metadata["questCatalogAvailable"], True)
            self.assertEqual(metadata["questCatalogRecordCount"], 1)
            self.assertEqual(metadata["questReferenceStatusCounts"], {"unresolved": 1})
            self.assertEqual(metadata["referenceIssueKindCounts"], {"quest-reference-unresolved": 1})
            for name in (
                "catalog.json",
                "acquisition-records.nedb",
                "dataset-issues.nedb",
                "reference-issues.nedb",
                "unclassified-evidence.nedb",
                "dataset-metadata.json",
            ):
                self.assertTrue((output / name).is_file(), name)


    def test_offline_raw_parse_persists_all_operator_stops(self):
        page_html = _page(
            '<ul><li><a href="/kancolle/Glorious(未確定)">Glorious</a>の初期装備</li></ul>',
            no=567,
        )
        catalog = ShipReferenceCatalog(
            Start2ShipUtils([
                {"api_id": 1022, "api_sortno": 1022, "api_name": "Glorious"},
                {"api_id": 1027, "api_sortno": 1027, "api_name": "Glorious"},
            ]),
            kcwiki_ship_path=None,
        )
        with tempfile.TemporaryDirectory() as temp_name:
            temp = Path(temp_name)
            raw_root = temp / "raw"
            output = temp / "output"
            cache_key = "wikiwiki.jp/kancolle/sea-gladiator.html"
            raw_path = raw_root / cache_key
            raw_path.parent.mkdir(parents=True)
            raw_path.write_text(page_html, encoding="utf-8")
            import hashlib
            digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            (raw_root / "_meta.json").write_text(
                json.dumps({
                    cache_key: {
                        "url": "https://wikiwiki.jp/kancolle/Sea%20Gladiator",
                        "status_code": 200,
                        "fetch_status": "fresh",
                        "content_sha256": digest,
                        "acquisition_source": "external-browser-session-crawl",
                        "equipmentId": 567,
                        "equipmentName": "Sea Gladiator",
                    }
                }),
                encoding="utf-8",
            )
            with mock.patch(
                "service.data_package.equipment_acquisition_raw_parse.player_equipment_items",
                return_value=[{
                    "api_id": 567,
                    "api_sortno": 567,
                    "api_name": "Sea Gladiator",
                }],
            ), mock.patch(
                "service.data_package.equipment_acquisition_raw_parse.ShipReferenceCatalog.load",
                return_value=catalog,
            ):
                with self.assertRaisesRegex(
                    Exception, "ship reference could not be mapped"
                ):
                    run_offline_parse(
                        raw_root=raw_root,
                        output_dir=output,
                        quest_catalog_text="{}",
                    )
            primary = json.loads((output / "operator-stop.json").read_text("utf-8"))
            self.assertEqual(primary["stopReason"], "ship-reference-ambiguous")
            self.assertEqual(primary["details"]["operatorStopCount"], 1)
            all_stops = (output / "operator-stops.nedb").read_text("utf-8").splitlines()
            self.assertEqual(len(all_stops), 1)

    def test_offline_raw_parse_uses_shared_cache_without_network(self):
        page_html = _page("<ul><li>開発可能。</li><li>任務『防空駆逐艦、参戦！』報酬</li></ul>", no=3)
        quest_catalog = '{"1234":{"code":"F123","name":"防空駆逐艦、参戦！"}}'
        with tempfile.TemporaryDirectory() as temp_name:
            temp = Path(temp_name)
            raw_root = temp / "raw"
            output = temp / "output"
            cache_key = "wikiwiki.jp/kancolle/test-3.html"
            raw_path = raw_root / cache_key
            raw_path.parent.mkdir(parents=True)
            raw_path.write_text(page_html, encoding="utf-8")
            import hashlib
            digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            (raw_root / "_meta.json").write_text(
                json.dumps({
                    cache_key: {
                        "url": "https://wikiwiki.jp/kancolle/test-3",
                        "status_code": 200,
                        "fetch_status": "fresh",
                        "content_sha256": digest,
                        "acquisition_source": "external-browser-session-crawl",
                        "equipmentId": 3,
                        "equipmentName": "10cm連装高角砲",
                    }
                }),
                encoding="utf-8",
            )
            with mock.patch(
                "service.data_package.equipment_acquisition_raw_parse.player_equipment_items",
                return_value=[{"api_id": 3, "api_sortno": 3, "api_name": "10cm連装高角砲"}],
            ):
                metadata = run_offline_parse(
                    raw_root=raw_root,
                    output_dir=output,
                    quest_catalog_text=quest_catalog,
                )
            self.assertEqual(metadata["mode"], "offline-raw-cache-parse")
            self.assertEqual(metadata["recordCount"], 1)
            self.assertEqual(metadata["acceptedRecordCount"], 1)
            self.assertEqual(metadata["rawCaptureCount"], 1)
            self.assertEqual(metadata["missingRawCaptureCount"], 0)
            self.assertIs(metadata["networkAccess"], False)
            record = json.loads((output / "acquisition-records.nedb").read_text().strip())
            self.assertEqual(record["rawEvidence"]["cacheKey"], cache_key)
            self.assertEqual(record["resolvedQuestKeys"], [1234])


if __name__ == "__main__":
    unittest.main()
