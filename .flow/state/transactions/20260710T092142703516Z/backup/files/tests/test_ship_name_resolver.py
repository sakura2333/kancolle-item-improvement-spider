import json
import os
import unittest

from pojo.improvement import ShipWeek
from service.akashi_list.akashi_list_utils import build_assistant_ship_ids_by_day
from service.akashi_list.ship_name_resolver import ShipNameResolver
from util.start2.config import start2_dir
from util.start2.start2_ship_utils import Start2ShipUtils


class ShipNameResolverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ship_utils = Start2ShipUtils(os.path.join(start2_dir, "api_mst_ship.json"))
        cls.resolver = ShipNameResolver(cls.ship_utils)

    def assert_ids(self, text, expected, anchor=None):
        actual = self.resolver.resolve(text, fallback_anchor_id=anchor).ship_ids
        self.assertEqual(expected, actual, text)

    def test_current_irregular_syntax(self):
        self.assert_ids("夕張改二/特/丁", [622, 623, 624], 622)
        self.assert_ids("吹雪(改三/護不可)", [9, 201, 426], 9)
        self.assert_ids("龍鳳(改～不可)", [185], 185)
        self.assert_ids("最上/改二特(改二不可)", [70, 73, 506], 70)
        self.assert_ids("雪風/改/改二", [20, 228, 651, 656], 20)
        self.assert_ids("宗谷(特務艦のみ)", [699], 699)

    def test_conversion_cycle_has_forward_stage_order(self):
        self.assert_ids("鈴谷改二", [503, 508], 503)
        self.assert_ids("鈴谷航改二", [508], 508)
        self.assert_ids("夕張改二特", [623, 624], 623)
        self.assert_ids("夕張改二丁", [624], 624)

    def test_more_specific_week_rule_overrides_ancestor(self):
        base = self.resolver.resolve("鳳翔", fallback_anchor_id=89)
        kai2 = self.resolver.resolve("鳳翔改二", fallback_anchor_id=894)
        rules = [
            ShipWeek(
                text="鳳翔",
                week=[True] * 7,
                ship_id_list=base.ship_ids,
                match_distance_by_id=base.match_distance_by_id,
            ),
            ShipWeek(
                text="鳳翔改二",
                week=[True, True, False, False, True, True, True],
                ship_id_list=kai2.ship_ids,
                match_distance_by_id=kai2.match_distance_by_id,
            ),
        ]
        by_day = build_assistant_ship_ids_by_day(rules)
        self.assertEqual([89, 285, 894, 899], by_day[0])
        self.assertEqual([89, 285], by_day[3])  # Tuesday
        self.assertEqual([89, 285], by_day[4])  # Wednesday

    def test_no_specific_ship_is_distinct_from_unavailable(self):
        rules = [
            ShipWeek(
                text="",
                week=[True, False, False, False, False, False, False],
                ship_id_list=[],
            ),
        ]
        by_day = build_assistant_ship_ids_by_day(rules)
        self.assertEqual([], by_day[0])
        self.assertEqual([], by_day[1])
        self.assertIsNone(by_day[2])

    def test_every_existing_rule_resolves(self):
        source = os.path.join(os.path.dirname(start2_dir), "improvement", "improvement-detail.nedb")
        with open(source, "r", encoding="utf-8") as file:
            records = [json.loads(line) for line in file if line.strip()]

        for item in records:
            for improvement in item.get("improvementList", []):
                for ship_week in improvement.get("shipWeekList", []):
                    self.assertEqual("resolved", ship_week.get("parseStatus"))
                    if ship_week.get("text"):
                        self.assertTrue(ship_week.get("shipIdList"), ship_week.get("text"))


if __name__ == "__main__":
    unittest.main()
