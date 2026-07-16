from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from script.project import run_command
from script.project.source_phase import SourceTaskResult


class RunFlowCommandTest(unittest.TestCase):
    def test_run_completes_start2_then_parallel_sources_before_data_processing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            report = root / "dist/data-pipeline/local-validation.json"
            report.parent.mkdir(parents=True)
            report.write_text('{"sourceReliability":{"sources":[]}}\n', encoding="utf-8")
            calls: list[tuple[str, list[str]]] = []
            source_tasks = []

            def fake_run_logged(_root, command, label):
                calls.append((label, list(command)))
                return root / f".flow/state/logs/{label}.log"

            def fake_run_source_tasks(_root, tasks):
                source_tasks.extend(tasks)
                return [
                    SourceTaskResult(task.name, task.label, root / f".flow/state/logs/{task.label}.log")
                    for task in tasks
                ]

            with mock.patch.object(run_command, "run_logged", side_effect=fake_run_logged), \
                    mock.patch.object(run_command, "run_source_tasks", side_effect=fake_run_source_tasks):
                result = run_command.run(root, [], {}, None)

            self.assertEqual(result["exitCode"], 0)
            self.assertEqual([label for label, _ in calls], [
                "run-before-check",
                "run-start2",
                "data-validate",
            ])
            self.assertEqual([task.name for task in source_tasks], ["akashi-list", "wikiwiki-jp"])
            self.assertIn("akashi_command.py", " ".join(source_tasks[0].command))
            self.assertIn("full", source_tasks[0].command)
            self.assertIn("--skip-start2", source_tasks[0].command)
            self.assertIn("wikiwiki", source_tasks[1].command)
            self.assertIn("--full", source_tasks[1].command)
            self.assertIn("--skip-start2", source_tasks[1].command)
            self.assertIn("source acquisition", "\n".join(result["completed"]))


    def test_run_reuses_ready_wikiwiki_receipt_without_browser_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            report = root / "dist/data-pipeline/local-validation.json"
            report.parent.mkdir(parents=True)
            report.write_text('{"sourceReliability":{"sources":[]}}\n', encoding="utf-8")
            receipt = root / ".flow/local/wikiwiki-crawler/source-receipt.json"
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(json.dumps({
                "schemaVersion": 1,
                "source": "wikiwiki-jp",
                "ready": True,
                "indexes": {
                    "ship": {"status": "ready"},
                    "equipment": {"status": "ready"},
                    "improvement": {"status": "ready"},
                },
                "details": {
                    "equipment": {
                        "status": "ready",
                        "selected": 574,
                        "completed": 574,
                        "remaining": 0,
                        "failed": 0,
                        "sourceExcluded": 3,
                        "stopReason": None,
                    },
                    "ship": {"status": "deferred"},
                },
            }) + "\n", encoding="utf-8")
            source_tasks = []

            def fake_run_logged(_root, command, label):
                return root / f".flow/state/logs/{label}.log"

            def fake_run_source_tasks(_root, tasks):
                source_tasks.extend(tasks)
                return [
                    SourceTaskResult(task.name, task.label, root / f".flow/state/logs/{task.label}.log")
                    for task in tasks
                ]

            with mock.patch.object(run_command, "run_logged", side_effect=fake_run_logged), \
                    mock.patch.object(run_command, "run_source_tasks", side_effect=fake_run_source_tasks):
                result = run_command.run(root, [], {}, None)

            self.assertEqual(result["exitCode"], 0)
            self.assertEqual([task.name for task in source_tasks], ["akashi-list"])
            completed = "\n".join(result["completed"])
            self.assertIn("复用 ready receipt", completed)
            self.assertIn("selected=574", completed)

    def test_run_surfaces_wikiwiki_reference_diagnostics_in_normal_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            report = root / "dist/data-pipeline/local-validation.json"
            report.parent.mkdir(parents=True)
            report.write_text('{"sourceReliability":{"sources":[]}}\n', encoding="utf-8")
            diagnostic = root / "dist/data-pipeline/sources/wikiwiki-equipment-detail/reference-diagnostics.json"
            diagnostic.parent.mkdir(parents=True, exist_ok=True)
            diagnostic.write_text(json.dumps({
                "schemaVersion": 1,
                "source": "wikiwiki-equipment-detail",
                "status": "passed",
                "resolvedLinkTargetConflictCount": 1,
                "operatorStopReferenceCount": 0,
                "rows": [{
                    "category": "resolved-link-target-conflict",
                    "equipmentId": 21,
                    "equipmentName": "零式艦戦52型",
                    "rawName": "翔鶴",
                    "linkTarget": "翔鶴改",
                    "acceptedShip": {"shipId": 288, "shipName": "翔鶴改"},
                    "reason": "link-page-is-more-specific-than-visible-text",
                }],
            }) + "\n", encoding="utf-8")

            def fake_run_logged(_root, command, label):
                return root / f".flow/state/logs/{label}.log"

            with mock.patch.object(run_command, "run_logged", side_effect=fake_run_logged), \
                    mock.patch.object(run_command, "run_source_tasks", return_value=[]):
                result = run_command.run(root, [], {}, None)

            completed = "\n".join(result["completed"])
            self.assertIn("WikiWiki 解析诊断", completed)
            self.assertIn("已收敛 linkTarget 冲突=1", completed)
            self.assertIn("equipment=21:零式艦戦52型", completed)
            self.assertIn("accepted=288:翔鶴改", completed)


    def test_run_surfaces_improvement_assistant_reverse_index_in_normal_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            report = root / "dist/data-pipeline/local-validation.json"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text('{"sourceReliability":{"sources":[]}}\n', encoding="utf-8")
            reverse = root / "dist/data-pipeline/sources/improvement-assistant-reverse/assistant-day-reverse-index.json"
            reverse.parent.mkdir(parents=True, exist_ok=True)
            reverse.write_text(json.dumps({
                "schemaVersion": 1,
                "threshold": 3,
                "expectedEquipmentCount": 3,
                "equipmentCountMismatchShipDayCount": 1,
                "overThresholdShipDayCount": 1,
                "maxEquipmentCount": 4,
                "equipmentCountMismatches": [{
                    "dayIndex": 5,
                    "dayName": "木",
                    "shipId": 182,
                    "shipName": "明石改",
                    "equipmentCount": 4,
                    "equipments": [
                        {"equipmentId": 1, "equipmentName": "装備1"},
                        {"equipmentId": 2, "equipmentName": "装備2"},
                        {"equipmentId": 3, "equipmentName": "装備3"},
                        {"equipmentId": 4, "equipmentName": "装備4"},
                    ],
                }],
            }, ensure_ascii=False) + "\n", encoding="utf-8")

            def fake_run_logged(_root, command, label):
                return root / f".flow/state/logs/{label}.log"

            with mock.patch.object(run_command, "run_logged", side_effect=fake_run_logged), \
                    mock.patch.object(run_command, "run_source_tasks", return_value=[]):
                result = run_command.run(root, [], {}, None)

            completed = "\n".join(result["completed"])
            self.assertIn("改修秘书舰反查", completed)
            self.assertIn("不等于期望的舰/日=1", completed)
            self.assertIn("超过期望的舰/日=1", completed)
            self.assertIn("ship=182:明石改", completed)
            self.assertIn("equipmentCount=4", completed)
            self.assertIn("expected=3", completed)

    def test_run_rejects_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            result = run_command.run(Path(temp_name), ["--quick"], {}, None)
            self.assertEqual(result["exitCode"], 2)


if __name__ == "__main__":
    unittest.main()
