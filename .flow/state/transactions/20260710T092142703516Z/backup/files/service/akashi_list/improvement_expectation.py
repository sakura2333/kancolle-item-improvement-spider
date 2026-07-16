from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from pojo.improvement import ImprovementStage


_STAR_HEADER = re.compile(r"^★(\d+)$")
_SIMPLE_NUMBER = re.compile(r"^([+-]?\d+(?:\.\d+)?)(%)?$")
_STAGE_RANGE = re.compile(r"^★(\d+)~★(\d+)$")
_STAGE_SINGLE = re.compile(r"^★(\d+)$")


@dataclass
class _ActiveSpan:
    remaining_rows: int
    value: str


def _clean_text(node) -> str:
    return " ".join(node.xpath("string(.)").split())


def _expand_table(table_node) -> list[dict[str, Any]]:
    """Expand rowspan/colspan into a rectangular text grid.

    Akashi effect tables use rowspan for aliases such as 夜戦火力 and for
    conditional equipment-bonus rows. Direct child-cell counting therefore loses
    the level alignment. This expander keeps the source row class while restoring
    each logical column.
    """

    rows: list[dict[str, Any]] = []
    active: dict[int, _ActiveSpan] = {}

    for source_index, tr in enumerate(table_node.xpath("./tr")):
        cells = tr.xpath("./th|./td")
        row: list[str] = []
        column = 0

        def append_active_until(next_real_column: int | None = None):
            nonlocal column
            while column in active and (next_real_column is None or column < next_real_column):
                span = active[column]
                row.append(span.value)
                span.remaining_rows -= 1
                if span.remaining_rows <= 0:
                    del active[column]
                column += 1

        for cell in cells:
            append_active_until()
            value = _clean_text(cell)
            colspan = max(int(cell.get("colspan") or 1), 1)
            rowspan = max(int(cell.get("rowspan") or 1), 1)
            for offset in range(colspan):
                row.append(value)
                if rowspan > 1:
                    active[column + offset] = _ActiveSpan(rowspan - 1, value)
            column += colspan

        while active:
            if column in active:
                append_active_until()
                continue
            future_columns = [key for key in active if key > column]
            if not future_columns:
                break
            next_column = min(future_columns)
            row.extend([""] * (next_column - column))
            column = next_column

        rows.append({
            "sourceIndex": source_index,
            "className": tr.get("class") or "",
            "cells": row,
        })

    return rows


def _effect_value(name: str, value_text: str, row_index: int, conditional: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "valueText": value_text,
        "sourceRow": row_index,
    }
    if conditional:
        result["conditional"] = True
    match = _SIMPLE_NUMBER.fullmatch(value_text)
    if match:
        result["value"] = float(match.group(1))
        if match.group(2):
            result["unit"] = "%"
    return result


def empty_level_expectations() -> list[dict[str, Any]]:
    return [
        {
            "level": level,
            "label": "★MAX" if level == 10 else f"★{level}",
            "effects": [],
        }
        for level in range(11)
    ]


def parse_level_expectations(page_node) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Parse the single-equipment effect table into ★0..★MAX expectations.

    Values are intentionally source-faithful. Simple numeric and percent values
    also expose a numeric `value`; conditional or formula-like cells keep only
    `valueText` so consumers never mistake guessed arithmetic for source facts.
    """

    tables = page_node.xpath(
        "//div[contains(concat(' ', normalize-space(@class), ' '), ' remodel-table ')]/table"
    )
    fallback = None
    for table in tables:
        expanded = _expand_table(table)
        for row_index, row in enumerate(expanded):
            cells = row["cells"]
            if len(cells) < 11:
                continue
            headers = cells[:11]
            level_headers = [
                int(match.group(1))
                for text in headers[1:11]
                if (match := _STAR_HEADER.fullmatch(text))
            ]
            if level_headers != list(range(1, 11)):
                continue
            candidate = (table, expanded, row_index, headers[0])
            if headers[0] == "単一":
                fallback = candidate
                break
            if fallback is None:
                fallback = candidate
        if fallback is not None and fallback[3] == "単一":
            break

    levels = empty_level_expectations()
    if fallback is None:
        return ({"status": "unavailable"}, levels)

    table, expanded, header_index, profile_label = fallback
    title = ""
    if header_index > 0:
        title_cells = expanded[header_index - 1]["cells"]
        title = next((value for value in title_cells if value), "")

    for row in expanded[header_index + 1:]:
        cells = row["cells"]
        if len(cells) < 11:
            continue
        label = cells[0].strip()
        values = cells[1:11]
        if not label or not any(value.strip() for value in values):
            continue
        conditional = "rbonus-row" in row["className"].split()
        for level, raw_value in enumerate(values, start=1):
            value_text = raw_value.strip()
            if not value_text:
                continue
            levels[level]["effects"].append(
                _effect_value(label, value_text, row["sourceIndex"], conditional)
            )

    return (
        {
            "status": "ok",
            "profile": profile_label,
            "title": title,
            "source": "akashi-list",
        },
        levels,
    )


def _stage_levels(stage_text: str) -> Iterable[int]:
    range_match = _STAGE_RANGE.fullmatch(stage_text)
    if range_match:
        start, end = map(int, range_match.groups())
        return range(start, end + 1)
    single_match = _STAGE_SINGLE.fullmatch(stage_text)
    if single_match:
        return (int(single_match.group(1)),)
    return ()


def _level_label(level: int) -> str:
    return "★MAX" if level == 10 else f"★{level}"


def _recipe_payload(stage: ImprovementStage) -> dict[str, Any]:
    return {
        "sourceStageText": stage.stage_text,
        "industryResource": [
            stage.dev_normal,
            stage.dev_certain,
            stage.rev_normal,
            stage.rev_certain,
        ],
        "consumables": [value.to_json() for value in stage.consumable_list],
    }


def build_route_step_list(stages: list[ImprovementStage]) -> list[dict[str, Any]]:
    """Expand compact source ranges into fixed ★0..★MAX actions.

    Every route returns exactly eleven rows: ten normal improvement attempts and
    one MAX conversion slot. Missing source coverage is explicit (`available=false`)
    instead of being silently inferred by consumers.
    """

    stage_by_level: dict[int, ImprovementStage] = {}
    upgrade_stage: ImprovementStage | None = None
    for stage in stages:
        if stage.target_weapon.id > 0:
            upgrade_stage = stage
            continue
        for level in _stage_levels(stage.stage_text):
            if 0 <= level <= 9:
                stage_by_level[level] = stage

    result: list[dict[str, Any]] = []
    for from_level in range(10):
        to_level = from_level + 1
        stage = stage_by_level.get(from_level)
        row: dict[str, Any] = {
            "fromLevel": from_level,
            "fromLabel": _level_label(from_level),
            "action": "improve",
            "available": stage is not None,
            "expectedResult": {
                "kind": "level",
                "level": to_level,
                "label": _level_label(to_level),
            },
            "effectExpectationLevel": to_level,
        }
        if stage is not None:
            row.update(_recipe_payload(stage))
        result.append(row)

    upgrade: dict[str, Any] = {
        "fromLevel": 10,
        "fromLabel": "★MAX",
        "action": "upgrade",
        "available": upgrade_stage is not None,
    }
    if upgrade_stage is not None:
        upgrade.update(_recipe_payload(upgrade_stage))
        upgrade["expectedResult"] = {
            "kind": "weapon",
            "targetWeapon": upgrade_stage.target_weapon.to_json(),
        }
    result.append(upgrade)
    return result
