import json
import os
import unittest

from pojo.equip_item import WeaponItemVO
from pojo.improvement import ImprovementVO
from service.source_validation.common import schedules_from_primary
from service.source_validation.compare import compare_source
from service.source_validation.kcwiki_data import build_ship_reference_map, parse_kcwiki_data
from service.source_validation.model import SourceResult, SourceSchedule, normalize_week
from service.source_validation.semantic_aliases import (
    load_semantic_alias_dictionary,
    validate_semantic_alias_dictionary,
)
from service.source_validation.wikiwiki_jp import parse_wikiwiki_html
from util.start2.config import start2_dir
from util.start2.start2_item_utils import Start2ItemUtils
from util.start2.start2_ship_utils import Start2ShipUtils


class SourceValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(start2_dir, "api_mst_slotitem.json"), "r", encoding="utf-8") as file:
            cls.item_utils = Start2ItemUtils(json.load(file))
        cls.ship_utils = Start2ShipUtils(os.path.join(start2_dir, "api_mst_ship.json"))

    def test_primary_projection_distinguishes_no_helper(self):
        item = WeaponItemVO(id=122, name="10cm連装高角砲+高射装置")
        item.improvement_list = [ImprovementVO(
            assistant_ship_ids_by_day=[
                [330],
                [330],
                [],
                None,
                None,
                None,
                None,
                None,
            ],
        )]
        schedules = schedules_from_primary([item], self.ship_utils)
        indexed = {(value.item_id, value.ship_id): value for value in schedules}
        self.assertEqual((True, False, False, False, False, False, False), indexed[(122, 330)].week)
        self.assertEqual((False, True, False, False, False, False, False), indexed[(122, None)].week)

    def test_wikiwiki_table_parser_expands_rows_and_resolves_names(self):
        html = """
        <html><body><table>
          <tr><th rowspan="2">改修する装備</th><th colspan="7">曜日</th><th rowspan="2">二番艦</th></tr>
          <tr><th>日</th><th>月</th><th>火</th><th>水</th><th>木</th><th>金</th><th>土</th></tr>
          <tr><td rowspan="2">10cm連装高角砲+高射装置</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>×</td><td>×</td><td>×</td><td>秋月</td></tr>
          <tr><td>×</td><td>×</td><td>×</td><td>×</td><td>◯</td><td>◯</td><td>◯</td><td>照月</td></tr>
        </table></body></html>
        """
        result = parse_wikiwiki_html(html, self.item_utils, self.ship_utils, "fixture://wikiwiki")
        self.assertEqual("ok", result.status)
        self.assertFalse(result.issues)
        by_name = {schedule.ship_name: schedule.week for schedule in result.schedules}
        # A named base form follows the same forward-remodel semantics as the Japanese Wiki.
        self.assertEqual((True, True, True, True, False, False, False), by_name["秋月"])
        self.assertEqual((False, False, False, False, True, True, True), by_name["照月"])


    def test_semantic_alias_dictionary_matches_current_start2(self):
        dictionary = load_semantic_alias_dictionary()
        validation = validate_semantic_alias_dictionary(self.item_utils, self.ship_utils)
        self.assertEqual(6, len(dictionary.entries))
        self.assertEqual(6, validation["validatedTargetCount"])
        souya = dictionary.lookup("wikiwiki-jp", "ship", "宗谷\n(特務艦)*")
        self.assertIsNotNone(souya)
        self.assertEqual(699, souya.canonical_id)
        self.assertEqual("特務艦", souya.qualifier)

    def test_wikiwiki_semantic_aliases_resolve_exact_forms_before_line_splitting(self):
        html = """
        <html><body><table>
          <tr><th rowspan="2">改修する装備</th><th colspan="7">曜日</th><th rowspan="2">二番艦</th></tr>
          <tr><th>日</th><th>月</th><th>火</th><th>水</th><th>木</th><th>金</th><th>土</th></tr>
          <tr><td>SG レーダー(初期型)</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>Fletcher<br/>改 Mod.2</td></tr>
          <tr><td>SG レーダー(初期型)</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>FletcherMkII</td></tr>
          <tr><td>SG レーダー(初期型)</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>宗谷<br/>(特務艦)*</td></tr>
          <tr><td>SG レーダー(初期型)</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>◯</td><td>加賀<br/>改二護</td></tr>
        </table></body></html>
        """
        result = parse_wikiwiki_html(html, self.item_utils, self.ship_utils, "fixture://wikiwiki")
        self.assertEqual("ok", result.status)
        self.assertFalse(result.issues)
        self.assertEqual(4, result.metadata["semanticAliasMatchCount"])
        self.assertEqual({628, 629, 646, 699}, {row.ship_id for row in result.schedules})

    def test_wikiwiki_unresolved_name_marks_source_partial(self):
        html = """
        <html><body><table>
          <tr><th>改修する装備</th><th>日</th><th>月</th><th>火</th><th>水</th><th>木</th><th>金</th><th>土</th><th>二番艦</th></tr>
          <tr><td>SG レーダー(初期型)</td><td>◯</td><td>×</td><td>×</td><td>×</td><td>×</td><td>×</td><td>×</td><td>未知艦</td></tr>
        </table></body></html>
        """
        result = parse_wikiwiki_html(html, self.item_utils, self.ship_utils, "fixture://wikiwiki")
        self.assertEqual("partial", result.status)
        self.assertEqual(1, result.metadata["unresolvedShipCount"])

    def test_kcwiki_structured_parser(self):
        equipment = {
            "10cm Twin High-angle Gun Mount + Anti-Aircraft Fire Director": {
                "_id": 122,
                "_japanese_name": "10cm連装高角砲+高射装置",
                "_improvements": {
                    "_products": {
                        "false": {
                            "0": {
                                "_ships": {
                                    "Akizuki/": {
                                        "Sunday": True,
                                        "Monday": True,
                                        "Tuesday": False,
                                        "Wednesday": False,
                                        "Thursday": False,
                                        "Friday": False,
                                        "Saturday": False,
                                    },
                                    "Akizuki/Kai": {
                                        "Sunday": False,
                                        "Monday": False,
                                        "Tuesday": True,
                                        "Wednesday": True,
                                        "Thursday": False,
                                        "Friday": False,
                                        "Saturday": False,
                                    },
                                }
                            }
                        }
                    }
                },
            }
        }
        ship = {
            "Akizuki": {
                "_api_id": 330,
                "_japanese_name": "秋月",
                "_name": "Akizuki",
                "_remodels": {
                    "Kai": {
                        "_api_id": 421,
                        "_japanese_name": "秋月改",
                        "_name": "Akizuki Kai",
                    }
                },
            }
        }
        result = parse_kcwiki_data(
            equipment,
            ship,
            self.item_utils,
            self.ship_utils,
            "fixture://kcwiki",
        )
        self.assertFalse(result.issues)
        by_id = {schedule.ship_id: schedule.week for schedule in result.schedules}
        base_id = int(self.ship_utils.get_by_name("秋月")["api_id"])
        remodel_id = int(self.ship_utils.get_by_name("秋月改")["api_id"])
        self.assertEqual((True, True, False, False, False, False, False), by_id[base_id])
        self.assertEqual((False, False, True, True, False, False, False), by_id[remodel_id])


    def test_kcwiki_ship_aliases_cover_slash_remodel_references(self):
        ship_catalog = {
            "Fubuki": {
                "_api_id": 9,
                "_name": "Fubuki",
                "_full_name": "Fubuki",
                "_japanese_name": "吹雪",
            },
            "Fubuki Kai": {
                "_api_id": 201,
                "_name": "Fubuki",
                "_full_name": "Fubuki Kai",
                "_japanese_name": "吹雪改",
            },
            "Fubuki Kai Ni": {
                "_api_id": 426,
                "_name": "Fubuki",
                "_full_name": "Fubuki Kai Ni",
                "_japanese_name": "吹雪改二",
            },
        }
        aliases = build_ship_reference_map(ship_catalog, self.ship_utils)
        self.assertEqual(aliases["fubuki/kai"], [201])
        self.assertEqual(aliases["fubuki/kai ni"], [426])

    def test_kcwiki_true_ship_reference_means_no_specific_helper(self):
        equipment = {
            "12.7cm Twin Gun Mount": {
                "_id": 2,
                "_japanese_name": "12.7cm連装砲",
                "_improvements": {
                    "_products": {
                        "false": {
                            "_ships": {
                                "true": {
                                    "Sunday": True,
                                    "Monday": True,
                                    "Tuesday": True,
                                    "Wednesday": True,
                                    "Thursday": True,
                                    "Friday": True,
                                    "Saturday": True,
                                }
                            }
                        }
                    }
                },
            }
        }
        result = parse_kcwiki_data(
            equipment,
            {},
            self.item_utils,
            self.ship_utils,
            "fixture://kcwiki",
        )
        self.assertFalse(result.issues)
        self.assertEqual(result.schedules[0].ship_id, None)
        self.assertEqual(result.schedules[0].ship_name, "")


    def test_comparison_reports_weekday_mismatch(self):
        left = SourceResult(
            source="akashi-list",
            url="fixture://left",
            schedules=[SourceSchedule(
                source="akashi-list",
                item_id=1,
                item_name="item",
                ship_id=1,
                ship_name="ship",
                week=normalize_week([True, False, False, False, False, False, False]),
            )],
        )
        right = SourceResult(
            source="other",
            url="fixture://right",
            schedules=[SourceSchedule(
                source="other",
                item_id=1,
                item_name="item",
                ship_id=1,
                ship_name="ship",
                week=normalize_week([False, True, False, False, False, False, False]),
            )],
        )
        diffs, summary = compare_source(left, right)
        self.assertEqual(1, summary["weekdayMismatchCount"])
        self.assertEqual("weekday-mismatch", diffs[0].status)


if __name__ == "__main__":
    unittest.main()
