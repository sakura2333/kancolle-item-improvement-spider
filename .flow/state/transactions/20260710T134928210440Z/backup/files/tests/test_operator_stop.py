from __future__ import annotations

import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from service.operator_stop import (
    ANSI_RED,
    OperatorStopError,
    write_operator_stop,
    write_operator_stop_files,
)


class OperatorStopTest(unittest.TestCase):
    @staticmethod
    def _error(equipment_id: int, equipment_name: str) -> OperatorStopError:
        return OperatorStopError(
            stop_reason="ship-reference-ambiguous",
            message="ship reference could not be mapped to one Start2 ship ID",
            action="检查引用绑定的 Wiki 链接目标，补充明确形态后重试。",
            checkpoint=".flow/local/source-cache/_meta.json",
            details={
                "equipmentId": equipment_id,
                "equipmentName": equipment_name,
                "sourceUrl": f"https://wikiwiki.jp/kancolle/{equipment_name}",
                "reference": {
                    "rawName": "Glorious",
                    "candidateShipIds": [1022, 1027],
                    "candidateShipNames": [
                        "Glorious(巡洋戦艦)",
                        "Glorious(航空母艦)",
                    ],
                    "candidateShips": [
                        {"shipId": 1022, "shipName": "Glorious(巡洋戦艦)"},
                        {"shipId": 1027, "shipName": "Glorious(航空母艦)"},
                    ],
                    "shipPageCrossValidation": {
                        "status": "rejected",
                        "reason": "ambiguous-visible-text-without-known-link-target",
                        "selectedShip": None,
                        "candidateShips": [
                            {"shipId": 1022, "shipName": "Glorious(巡洋戦艦)"},
                            {"shipId": 1027, "shipName": "Glorious(航空母艦)"},
                        ],
                    },
                },
            },
        )

    def test_writes_deduplicated_primary_and_all_stop_files(self):
        with tempfile.TemporaryDirectory() as temp_name:
            output = Path(temp_name)
            first = self._error(566, "10.2cm三連装副砲")
            duplicate = self._error(566, "10.2cm三連装副砲")
            second = self._error(567, "Sea Gladiator")
            primary, unique = write_operator_stop_files(
                [first, duplicate, second], output_dir=output
            )
            self.assertIsNotNone(primary)
            self.assertEqual(len(unique), 2)
            payload = json.loads((output / "operator-stop.json").read_text("utf-8"))
            self.assertEqual(payload["stopReason"], "ship-reference-ambiguous")
            self.assertEqual(payload["details"]["operatorStopCount"], 2)
            lines = [
                json.loads(line)
                for line in (output / "operator-stops.nedb").read_text("utf-8").splitlines()
            ]
            self.assertEqual(len(lines), 2)
            self.assertEqual(
                [line["details"]["equipmentId"] for line in lines], [566, 567]
            )

    def test_forced_color_and_stop_summaries_are_printed(self):
        with tempfile.TemporaryDirectory() as temp_name:
            primary, _ = write_operator_stop_files(
                [self._error(566, "10.2cm三連装副砲"), self._error(567, "Sea Gladiator")],
                output_dir=Path(temp_name),
            )
            stream = StringIO()
            write_operator_stop(primary, stream=stream, color=True)
            text = stream.getvalue()
            self.assertIn(f"{ANSI_RED}ERROR", text)
            self.assertIn("停止项: 2", text)
            self.assertIn("equipment=566:10.2cm三連装副砲", text)
            self.assertIn("equipment=567:Sea Gladiator", text)
            self.assertIn("candidates=1022:Glorious(巡洋戦艦),1027:Glorious(航空母艦)", text)
            self.assertIn("crossValidation=rejected:ambiguous-visible-text-without-known-link-target", text)

    def test_success_cleanup_removes_stale_stop_files(self):
        with tempfile.TemporaryDirectory() as temp_name:
            output = Path(temp_name)
            write_operator_stop_files([self._error(566, "x")], output_dir=output)
            write_operator_stop_files([], output_dir=output)
            self.assertFalse((output / "operator-stop.json").exists())
            self.assertFalse((output / "operator-stops.nedb").exists())


if __name__ == "__main__":
    unittest.main()
