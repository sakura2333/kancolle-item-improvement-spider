import unittest
from pathlib import Path

from lxml import etree

from pojo.improvement import ConsumeItem, ImprovementStage, TargetWeapon
from service.akashi_list.improvement_expectation import (
    build_route_step_list,
    parse_level_expectations,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "akashi"
CACHE_DIR = Path(__file__).parent / "fixtures" / "akashi"


class ImprovementExpectationTest(unittest.TestCase):
    def test_single_effect_table_expands_zero_through_max(self):
        root = etree.HTML((FIXTURE_DIR / "w021.html").read_text(encoding="utf-8"))
        source, levels = parse_level_expectations(root)

        self.assertEqual("ok", source["status"])
        self.assertEqual("単一", source["profile"])
        self.assertEqual(list(range(11)), [row["level"] for row in levels])
        self.assertEqual("★0", levels[0]["label"])
        self.assertEqual("★MAX", levels[10]["label"])
        self.assertEqual([], levels[0]["effects"])
        anti_air = next(effect for effect in levels[10]["effects"] if effect["name"] == "対空")
        self.assertEqual("+2.0", anti_air["valueText"])
        self.assertEqual(2.0, anti_air["value"])

    def test_rowspan_conditional_effects_keep_level_alignment(self):
        root = etree.HTML((CACHE_DIR / "w061.html").read_text(encoding="utf-8"))
        _, levels = parse_level_expectations(root)

        level_ten = levels[10]["effects"]
        hiryu = [effect for effect in level_ten if effect["name"] == "飛龍改二"]
        self.assertEqual(["火力+4", "索敵+5"], [effect["valueText"] for effect in hiryu])
        self.assertTrue(all(effect["conditional"] for effect in hiryu))

    def test_missing_effect_table_is_explicit(self):
        root = etree.HTML((CACHE_DIR / "w041.html").read_text(encoding="utf-8"))
        source, levels = parse_level_expectations(root)
        self.assertEqual({"status": "unavailable"}, source)
        self.assertEqual(11, len(levels))
        self.assertTrue(all(not row["effects"] for row in levels))

    def test_route_steps_expand_each_level_and_max_upgrade(self):
        early = ImprovementStage(
            stage_text="★0~★5",
            dev_normal=1,
            dev_certain=2,
            rev_normal=3,
            rev_certain=4,
            consumable_list=[ConsumeItem(id=19, count=1, type=0)],
        )
        late = ImprovementStage(
            stage_text="★6~★9",
            dev_normal=5,
            dev_certain=6,
            rev_normal=7,
            rev_certain=8,
        )
        upgrade = ImprovementStage(
            dev_normal=9,
            dev_certain=10,
            rev_normal=11,
            rev_certain=12,
            target_weapon=TargetWeapon(id=228, level=2, name="12cm単装砲改二"),
        )

        steps = build_route_step_list([early, late, upgrade])
        self.assertEqual(11, len(steps))
        self.assertEqual(list(range(11)), [step["fromLevel"] for step in steps])
        self.assertEqual(1, steps[0]["expectedResult"]["level"])
        self.assertEqual("★MAX", steps[9]["expectedResult"]["label"])
        self.assertEqual([1, 2, 3, 4], steps[5]["industryResource"])
        self.assertEqual([5, 6, 7, 8], steps[6]["industryResource"])
        self.assertEqual("upgrade", steps[10]["action"])
        self.assertEqual(
            {"id": 228, "level": 2, "name": "12cm単装砲改二"},
            steps[10]["expectedResult"]["targetWeapon"],
        )

    def test_route_without_conversion_still_has_max_slot(self):
        stage = ImprovementStage(stage_text="★0~★5")
        late = [ImprovementStage(stage_text=f"★{level}") for level in range(6, 10)]
        steps = build_route_step_list([stage, *late])
        self.assertFalse(steps[10]["available"])
        self.assertNotIn("expectedResult", steps[10])


if __name__ == "__main__":
    unittest.main()
