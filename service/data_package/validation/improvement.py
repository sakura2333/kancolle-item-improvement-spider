from __future__ import annotations

import math
from pathlib import Path

from .common import QualityGateError, _non_empty_string, _positive_int, _read_json, _read_nedb

def _validate_improvement_list(path: Path) -> tuple[int, int, set[int]]:
    document = _read_json(path)
    if not isinstance(document, dict):
        raise QualityGateError("improvement/list.json must contain an object")
    metadata = document.get("metadata")
    views = document.get("data")
    if not isinstance(metadata, dict) or not isinstance(views, list) or len(views) != 8:
        raise QualityGateError("improvement/list.json must contain metadata and exactly 8 views")
    if metadata.get("schemaVersion") != 2:
        raise QualityGateError(f"unsupported improvement list schema: {metadata.get('schemaVersion')!r}")
    if metadata.get("rowSchema") != ["itemId", "assistantTexts"]:
        raise QualityGateError("improvement list rowSchema changed unexpectedly")

    all_ids: set[int] = set()
    for view_index, rows in enumerate(views):
        if not isinstance(rows, list):
            raise QualityGateError(f"improvement list view {view_index} is not an array")
        seen: set[int] = set()
        for row_index, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != 2:
                raise QualityGateError(f"invalid improvement list row at view {view_index}, row {row_index}")
            item_id, assistants = row
            if not _positive_int(item_id) or not isinstance(assistants, list):
                raise QualityGateError(f"invalid improvement list row values at view {view_index}, row {row_index}")
            if item_id in seen:
                raise QualityGateError(f"duplicate equipment id {item_id} in improvement list view {view_index}")
            if any(not isinstance(name, str) for name in assistants):
                raise QualityGateError(f"assistant names must be strings for equipment {item_id}")
            seen.add(item_id)
            if view_index == 0:
                all_ids.add(item_id)
    if metadata.get("itemCount") != len(views[0]):
        raise QualityGateError(
            f"improvement list metadata itemCount={metadata.get('itemCount')!r} does not match {len(views[0])}"
        )
    return len(views), len(views[0]), all_ids

def _validate_improvement_detail(path: Path) -> tuple[int, set[int], set[int], dict[str, int]]:
    records = _read_nedb(path)
    ids: set[int] = set()
    required_useitem_ids: set[int] = set()
    effect_available_count = 0
    effect_unavailable_count = 0
    route_count = 0
    step_count = 0
    upgrade_available_count = 0
    for index, record in enumerate(records):
        item_id = record.get("id")
        if not _positive_int(item_id):
            raise QualityGateError(f"improvement detail record {index} has invalid id")
        if item_id in ids:
            raise QualityGateError(f"duplicate improvement detail id {item_id}")
        if not _non_empty_string(record.get("name")):
            raise QualityGateError(f"improvement detail {item_id} has no name")
        effect_source = record.get("effectSource")
        if not isinstance(effect_source, dict) or effect_source.get("status") not in {"ok", "unavailable"}:
            raise QualityGateError(f"improvement detail {item_id} has invalid effectSource")
        if effect_source["status"] == "ok":
            effect_available_count += 1
        else:
            effect_unavailable_count += 1
        expectations = record.get("levelExpectations")
        if not isinstance(expectations, list) or len(expectations) != 11:
            raise QualityGateError(f"improvement detail {item_id} must expose ★0..★MAX expectations")
        effect_count = 0
        for level, expectation in enumerate(expectations):
            if not isinstance(expectation, dict) or expectation.get("level") != level:
                raise QualityGateError(f"improvement detail {item_id} has invalid level expectation {level}")
            expected_label = "★MAX" if level == 10 else f"★{level}"
            if expectation.get("label") != expected_label or not isinstance(expectation.get("effects"), list):
                raise QualityGateError(f"improvement detail {item_id} has invalid expectation label/effects at {level}")
            if level == 0 and expectation["effects"]:
                raise QualityGateError(f"improvement detail {item_id} ★0 expectation must be the empty baseline")
            for effect in expectation["effects"]:
                effect_count += 1
                if not isinstance(effect, dict) or not _non_empty_string(effect.get("name")) or not _non_empty_string(effect.get("valueText")):
                    raise QualityGateError(f"improvement detail {item_id} has invalid effect at level {level}")
                if not isinstance(effect.get("sourceRow"), int) or effect["sourceRow"] < 0:
                    raise QualityGateError(f"improvement detail {item_id} has invalid effect source row at level {level}")
                if "value" in effect and (not isinstance(effect["value"], (int, float)) or isinstance(effect["value"], bool) or not math.isfinite(effect["value"])):
                    raise QualityGateError(f"improvement detail {item_id} has invalid numeric effect at level {level}")
                if "conditional" in effect and not isinstance(effect["conditional"], bool):
                    raise QualityGateError(f"improvement detail {item_id} has invalid conditional marker at level {level}")
        if effect_source["status"] == "unavailable" and effect_count:
            raise QualityGateError(f"improvement detail {item_id} unavailable effect source contains effects")
        if effect_source["status"] == "ok" and not effect_count:
            raise QualityGateError(f"improvement detail {item_id} effect source is ok but contains no effects")

        routes = record.get("improvementList")
        if not isinstance(routes, list) or not routes:
            raise QualityGateError(f"improvement detail {item_id} has no routes")
        for route_index, route in enumerate(routes):
            route_count += 1
            if not isinstance(route, dict):
                raise QualityGateError(f"improvement detail {item_id} route {route_index} is not an object")
            if not isinstance(route.get("stageList"), list) or not route["stageList"]:
                raise QualityGateError(f"improvement detail {item_id} route {route_index} has no stages")
            steps = route.get("stepList")
            if not isinstance(steps, list) or len(steps) != 11:
                raise QualityGateError(f"improvement detail {item_id} route {route_index} must expose 11 steps")
            step_count += len(steps)
            for from_level, step in enumerate(steps):
                if not isinstance(step, dict) or step.get("fromLevel") != from_level:
                    raise QualityGateError(f"improvement detail {item_id} route {route_index} has invalid step {from_level}")
                expected_from_label = "★MAX" if from_level == 10 else f"★{from_level}"
                if step.get("fromLabel") != expected_from_label:
                    raise QualityGateError(f"improvement detail {item_id} route {route_index} step {from_level} has invalid label")
                if not isinstance(step.get("available"), bool):
                    raise QualityGateError(f"improvement detail {item_id} route {route_index} step {from_level} lacks availability")
                if from_level < 10:
                    if step.get("action") != "improve" or not step["available"]:
                        raise QualityGateError(f"improvement detail {item_id} route {route_index} lacks level {from_level} recipe")
                    expected = step.get("expectedResult")
                    expected_level = from_level + 1
                    expected_label = "★MAX" if expected_level == 10 else f"★{expected_level}"
                    if (
                        not isinstance(expected, dict)
                        or expected.get("kind") != "level"
                        or expected.get("level") != expected_level
                        or expected.get("label") != expected_label
                    ):
                        raise QualityGateError(f"improvement detail {item_id} route {route_index} step {from_level} has invalid result")
                    if step.get("effectExpectationLevel") != expected_level:
                        raise QualityGateError(f"improvement detail {item_id} route {route_index} step {from_level} has invalid effect reference")
                    if not isinstance(step.get("industryResource"), list) or len(step["industryResource"]) != 4:
                        raise QualityGateError(f"improvement detail {item_id} route {route_index} step {from_level} lacks resource recipe")
                    if not isinstance(step.get("consumables"), list) or not _non_empty_string(step.get("sourceStageText")):
                        raise QualityGateError(f"improvement detail {item_id} route {route_index} step {from_level} lacks source recipe")
                else:
                    if step.get("action") != "upgrade":
                        raise QualityGateError(f"improvement detail {item_id} route {route_index} MAX slot is invalid")
                    if step["available"]:
                        upgrade_available_count += 1
                        expected = step.get("expectedResult")
                        target = expected.get("targetWeapon") if isinstance(expected, dict) else None
                        if (
                            expected.get("kind") != "weapon"
                            or not isinstance(target, dict)
                            or not _positive_int(target.get("id"))
                            or not _non_empty_string(target.get("name"))
                        ):
                            raise QualityGateError(f"improvement detail {item_id} route {route_index} MAX upgrade target is invalid")
                    elif "expectedResult" in step:
                        raise QualityGateError(f"improvement detail {item_id} route {route_index} unavailable MAX slot has a result")
            for stage_index, stage in enumerate(route["stageList"]):
                if not isinstance(stage, dict):
                    raise QualityGateError(
                        f"improvement detail {item_id} route {route_index} stage {stage_index} is not an object"
                    )
                consumables = stage.get("consumables", [])
                if not isinstance(consumables, list):
                    raise QualityGateError(
                        f"improvement detail {item_id} route {route_index} stage {stage_index} consumables are invalid"
                    )
                for consumable in consumables:
                    if not isinstance(consumable, dict):
                        raise QualityGateError(
                            f"improvement detail {item_id} route {route_index} stage {stage_index} has invalid consumable"
                        )
                    if consumable.get("type") == 1:
                        consumable_id = consumable.get("id")
                        if not _positive_int(consumable_id):
                            raise QualityGateError(
                                f"improvement detail {item_id} has invalid use-item consumable id {consumable_id!r}"
                            )
                        required_useitem_ids.add(consumable_id)
        ids.add(item_id)
    return len(records), ids, required_useitem_ids, {
        "effectExpectationAvailableCount": effect_available_count,
        "effectExpectationUnavailableCount": effect_unavailable_count,
        "routeCount": route_count,
        "stepCount": step_count,
        "upgradeAvailableCount": upgrade_available_count,
    }
