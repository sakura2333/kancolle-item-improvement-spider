from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from lxml import etree

from pojo.improvement import ShipWeek
from service.akashi_list.akashi_list_utils import build_assistant_ship_ids_by_day
from service.akashi_list.ship_name_resolver import ShipNameResolver
from service.source_validation.common import CatalogMatcher, merge_schedules, normalize_catalog_name
from service.source_validation.model import SourceIssue, SourceResult, SourceSchedule, normalize_week
from service.source_validation.semantic_aliases import resolve_semantic_alias
from util.cache import fetch
from util.start2.start2_item_utils import Start2ItemUtils
from util.start2.start2_ship_utils import Start2ShipUtils

SOURCE_ID = "wikiwiki-jp"
SOURCE_URL = "https://wikiwiki.jp/kancolle/%E6%94%B9%E4%BF%AE%E8%A1%A8"
DAY_LABELS = ["日", "月", "火", "水", "木", "金", "土"]
TRUE_MARKS = ("◯", "○", "〇", "△")
FALSE_MARKS = ("×", "✕", "✖")


@dataclass
class CellValue:
    text: str
    html: str


def _node_text_with_breaks(node) -> str:
    parts: List[str] = []

    def visit(current):
        if current.text:
            parts.append(current.text)
        for child in current:
            tag = child.tag.lower() if isinstance(child.tag, str) else ""
            if tag == "br":
                parts.append("\n")
            visit(child)
            if tag in {"div", "p", "li"}:
                parts.append("\n")
            if child.tail:
                parts.append(child.tail)

    visit(node)
    text = "".join(parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _cell_value(cell) -> CellValue:
    return CellValue(
        text=_node_text_with_breaks(cell),
        html=etree.tostring(cell, encoding="unicode", with_tail=False),
    )


def expand_table(table) -> List[List[CellValue]]:
    rows: List[List[CellValue]] = []
    active: Dict[int, Tuple[int, CellValue]] = {}

    for tr in table.xpath(".//tr"):
        row: List[CellValue] = []
        col = 0

        def consume_active():
            nonlocal col
            while col in active:
                remaining, value = active[col]
                while len(row) <= col:
                    row.append(CellValue("", ""))
                row[col] = value
                if remaining <= 1:
                    del active[col]
                else:
                    active[col] = (remaining - 1, value)
                col += 1

        consume_active()
        for cell in tr.xpath("./th|./td"):
            consume_active()
            value = _cell_value(cell)
            try:
                rowspan = max(1, int(cell.get("rowspan") or 1))
                colspan = max(1, int(cell.get("colspan") or 1))
            except ValueError:
                rowspan = colspan = 1

            for offset in range(colspan):
                target = col + offset
                while len(row) <= target:
                    row.append(CellValue("", ""))
                row[target] = value
                if rowspan > 1:
                    active[target] = (rowspan - 1, value)
            col += colspan
            consume_active()

        if active:
            max_col = max(active)
            while col <= max_col:
                if col in active:
                    consume_active()
                else:
                    while len(row) <= col:
                        row.append(CellValue("", ""))
                    col += 1
        rows.append(row)

    width = max((len(row) for row in rows), default=0)
    for row in rows:
        row.extend(CellValue("", "") for _ in range(width - len(row)))
    return rows


def _header_map(rows: Sequence[Sequence[CellValue]]) -> Optional[dict]:
    if not rows:
        return None
    width = max(len(row) for row in rows)
    scan_rows = rows[:6]
    labels_by_col = []
    for col in range(width):
        labels = []
        for row in scan_rows:
            text = row[col].text.strip() if col < len(row) else ""
            if text and text not in labels:
                labels.append(text)
        labels_by_col.append(" ".join(labels))

    item_col = next((idx for idx, text in enumerate(labels_by_col) if "改修する装備" in text), None)
    ship_col = next((idx for idx, text in enumerate(labels_by_col) if "二番艦" in text), None)
    day_cols: List[int] = []
    for label in DAY_LABELS:
        candidates = [
            idx for idx in range(width)
            if any((row[idx].text.strip() == label) for row in scan_rows if idx < len(row))
        ]
        day_cols.append(candidates[-1] if candidates else -1)

    if item_col is None or ship_col is None or any(col < 0 for col in day_cols):
        return None
    if len(set(day_cols)) != 7:
        return None
    return {"item": item_col, "ship": ship_col, "days": day_cols}


def _mark_enabled(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if any(mark in compact for mark in TRUE_MARKS):
        return True
    if any(mark in compact for mark in FALSE_MARKS):
        return False
    return False


def _helper_lines(text: str) -> List[str]:
    text = (text or "").strip()
    if not text or text == "-":
        return ["-"]
    lines = [line.strip() for line in re.split(r"[\n]+", text) if line.strip()]
    result = []
    for line in lines:
        line = re.sub(r"\*\d*$", "", line).strip()
        line = re.sub(r"^※", "", line).strip()
        if line and line not in result:
            result.append(line)
    return result or ["-"]


def parse_wikiwiki_html(
    html: str,
    item_utils: Start2ItemUtils,
    ship_utils: Start2ShipUtils,
    source_url: str = SOURCE_URL,
) -> SourceResult:
    root = etree.HTML(html)
    matcher = CatalogMatcher(item_utils, ship_utils)
    resolver = ShipNameResolver(ship_utils)
    issues: List[SourceIssue] = []
    rules_by_item: Dict[int, List[ShipWeek]] = defaultdict(list)
    item_names: Dict[int, str] = {}
    source_refs_by_item: Dict[int, List[str]] = defaultdict(list)
    table_count = 0
    parsed_row_count = 0
    semantic_alias_match_count = 0

    for table_index, table in enumerate(root.xpath("//table")):
        rows = expand_table(table)
        header = _header_map(rows)
        if not header:
            continue
        table_count += 1

        for row_index, row in enumerate(rows[1:], start=1):
            max_needed = max([header["item"], header["ship"], *header["days"]])
            if len(row) <= max_needed:
                continue
            week = [_mark_enabled(row[col].text) for col in header["days"]]
            if not any(week):
                continue

            item_text = row[header["item"]].text.split("\n", 1)[0].strip()
            item = matcher.item(item_text)
            source_ref = f"{source_url}#table-{table_index}-row-{row_index}"
            if item is None:
                issues.append(SourceIssue(
                    source=SOURCE_ID,
                    kind="unresolved-item",
                    message="equipment name was not found in start2",
                    source_ref=source_ref,
                    item_name=item_text,
                    raw_text=row[header["item"]].text,
                ))
                continue

            item_id = int(item["api_id"])
            item_name = str(item.get("api_name") or item_text)
            item_names[item_id] = item_name
            source_refs_by_item[item_id].append(source_ref)
            parsed_row_count += 1

            helper_text = row[header["ship"]].text.strip()
            full_cell_alias = resolve_semantic_alias(
                SOURCE_ID,
                "ship",
                helper_text,
                match_modes={"normalized-full-cell-exact"},
            )
            helpers = [helper_text] if full_cell_alias else _helper_lines(helper_text)
            for helper in helpers:
                if helper == "-":
                    rules_by_item[item_id].append(ShipWeek(
                        text="",
                        week=week,
                        ship_id_list=[],
                    ))
                    continue

                alias = full_cell_alias or resolve_semantic_alias(
                    SOURCE_ID,
                    "ship",
                    helper,
                    match_modes={"normalized-alias-exact"},
                )
                if alias is not None:
                    semantic_alias_match_count += 1
                    rules_by_item[item_id].append(ShipWeek(
                        text=helper_text if full_cell_alias else helper,
                        week=week,
                        ship_id_list=[alias.canonical_id],
                        anchor_ship_ids=[alias.canonical_id],
                        match_distance_by_id={alias.canonical_id: 0},
                    ))
                    continue

                try:
                    resolution = resolver.resolve(helper)
                except Exception as exc:
                    issues.append(SourceIssue(
                        source=SOURCE_ID,
                        kind="unresolved-ship",
                        message=str(exc),
                        source_ref=source_ref,
                        item_name=item_name,
                        ship_name=helper,
                        raw_text=helper_text,
                    ))
                    continue
                rules_by_item[item_id].append(ShipWeek(
                    text=helper,
                    week=week,
                    ship_id_list=resolution.ship_ids,
                    anchor_ship_ids=resolution.anchor_ship_ids,
                    match_distance_by_id=resolution.match_distance_by_id,
                ))

    schedules: List[SourceSchedule] = []
    for item_id, rules in rules_by_item.items():
        by_day = build_assistant_ship_ids_by_day(rules)
        week_by_ship: Dict[Optional[int], List[bool]] = {}
        for day in range(7):
            value = by_day[day + 1] if day + 1 < len(by_day) else None
            if value is None:
                continue
            if not value:
                week_by_ship.setdefault(None, [False] * 7)[day] = True
            else:
                for ship_id in value:
                    week_by_ship.setdefault(int(ship_id), [False] * 7)[day] = True

        for ship_id, week in week_by_ship.items():
            ship = ship_utils.get_by_id(ship_id) if ship_id is not None else None
            schedules.append(SourceSchedule(
                source=SOURCE_ID,
                item_id=item_id,
                item_name=item_names[item_id],
                ship_id=ship_id,
                ship_name=str((ship or {}).get("api_name") or "-"),
                week=normalize_week(week),
                route_id=f"wikiwiki-item-{item_id}",
                route_signature=f"wikiwiki-item-{item_id}",
                evidence_status="inferred-yes",
                parser_version="wikiwiki-table-v2",
                source_ref=source_refs_by_item[item_id][0],
                evidence={
                    "sourceRefCount": len(set(source_refs_by_item[item_id])),
                    "sharedInferenceRisk": True,
                },
            ))

    unresolved_ship_count = sum(1 for issue in issues if issue.kind == "unresolved-ship")
    unresolved_item_count = sum(1 for issue in issues if issue.kind == "unresolved-item")
    return SourceResult(
        source=SOURCE_ID,
        url=source_url,
        schedules=merge_schedules(schedules),
        issues=issues,
        status="partial" if issues else "ok",
        metadata={
            "supportedCapabilities": ["improve"],
            "tableCount": table_count,
            "parsedRowCount": parsed_row_count,
            "semanticAliasMatchCount": semantic_alias_match_count,
            "unresolvedShipCount": unresolved_ship_count,
            "unresolvedItemCount": unresolved_item_count,
        },
    )


def collect(item_utils: Start2ItemUtils, ship_utils: Start2ShipUtils) -> SourceResult:
    return parse_wikiwiki_html(fetch(SOURCE_URL), item_utils, ship_utils)
