from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence
from urllib.parse import quote, unquote, urljoin, urlparse

from lxml import etree

from service.data_package.equipment_acquisition_replacements import (
    canonical_acquisition_classification_text,
    canonical_acquisition_heading,
    is_acquisition_historical_marker,
    is_ignored_acquisition_text,
    resolve_acquisition_context_label,
)

SOURCE_ID = "wikiwiki-equipment-detail"
SOURCE_BASE_URL = "https://wikiwiki.jp/kancolle/"
CATALOG_PAGE_NAME = "装備カード一覧"
CATALOG_URL = SOURCE_BASE_URL + quote(CATALOG_PAGE_NAME, safe="")

_HEADING_RE = re.compile(r"^入手方法(?:について)?$")
_PAGE_ID_RE = re.compile(r"(?<!\d)No\.\s*0*(\d+)(?!\d)", re.IGNORECASE)
_CATALOG_LABEL_RE = re.compile(r"(?:No\.\s*)?0*(\d{1,4})\s*[:：]\s*(.+)")
_CATALOG_IMAGE_RE = re.compile(r"(?:weapon)?0*(\d{1,4})[a-z]?\.(?:png|jpe?g|webp)", re.IGNORECASE)
_HISTORICAL_RE = re.compile(
    r"過去の入手方法|これまでの入手方法|以前は|かつて|先行実装|"
    r"配布された|報酬だった|報酬として実装された|現在は入手不可|入手不能|終了済"
)

_HISTORICAL_MARKER_RE = re.compile(
    r"^(?:過去の入手方法|これまでの入手方法|以前の入手方法|"
    r"終了した.*(?:配布状況|入手方法)|これまでの.*配布状況)$"
)
_CURRENT_RE = re.compile(
    r"現在(?:は|も)?|現時点|恒常|入手可能|入手できる|建造可能|開発可能|"
    r"更新可能|継続中|実装中"
)
_TABLE_SHIP_CONTEXT_RE = re.compile(r"初期装備艦|持参艦|初期装備.*下表|所持艦.*下表")
_FALLBACK_HEADING_RE = re.compile(r"^ゲームにおいて$")
_FALLBACK_STOP_RE = re.compile(r"運用|改修工廠|装備ボーナス|性能比較|小ネタ|コメント")
_EXPLICIT_ACQUISITION_FACT_RE = re.compile(
    r"入手(?:可能|できる|出来る|手段)|"
    r"(?:報酬|褒賞)(?:として|で|[:：、。]|$)|"
    r"初期装備|持参"
)

_METHOD_PATTERNS: Sequence[tuple[str, re.Pattern[str]]] = (
    ("development", re.compile(r"開発")),
    ("ship", re.compile(r"初期装備|持参|牧場|所持艦|装備艦")),
    ("quest", re.compile(r"任務")),
    (
        "improvement",
        re.compile(
            r"改修更新|改修.*更新|更新先|★max.*更新|からの入手|"
            r"(?:から|より)の更新|更新で入手|改修で入手|改修による入手"
        ),
    ),
    ("ranking", re.compile(r"ランキング|作戦報酬|ランカー|聯合報酬")),
    ("event", re.compile(r"イベント|海域クリア報酬|突破報酬|期間限定海域")),
    ("construction", re.compile(r"建造")),
    ("purchase", re.compile(r"購入|アイテム屋")),
    ("exchange", re.compile(r"交換|選択報酬|選択式報酬")),
)


@dataclass(frozen=True)
class EquipmentCatalogEntry:
    equipment_id: int
    equipment_name: str
    page_name: str
    source_url: str

    def to_json(self) -> dict:
        return {
            "equipmentId": self.equipment_id,
            "equipmentName": self.equipment_name,
            "pageName": self.page_name,
            "sourceUrl": self.source_url,
        }


@dataclass(frozen=True)
class AcquisitionLink:
    text: str
    href: str

    def to_json(self) -> dict:
        return {"text": self.text, "href": self.href}


@dataclass
class AcquisitionMethod:
    types: List[str]
    availability: str
    raw_text: str
    links: List[AcquisitionLink] = field(default_factory=list)
    evidence_kind: str = "list-item"
    context: Optional[str] = None

    def to_json(self) -> dict:
        result = {
            "types": list(self.types),
            "availability": self.availability,
            "rawText": self.raw_text,
            "links": [link.to_json() for link in self.links],
            "evidenceKind": self.evidence_kind,
        }
        if self.context:
            result["context"] = self.context
        return result


@dataclass
class AcquisitionIssue:
    kind: str
    message: str
    evidence: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        result = {"source": SOURCE_ID, "kind": self.kind, "message": self.message}
        if self.evidence:
            result["evidence"] = self.evidence
        return result


def normalize_text(value: str) -> str:
    text = (value or "").replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def node_text(node) -> str:
    return normalize_text("".join(node.itertext()))


def build_page_name_candidates(equipment_name: str) -> List[str]:
    """Return conservative WikiWiki page-name candidates."""
    clean = normalize_text(equipment_name)
    candidates = [clean]
    variants = [
        clean.replace("+", "＋"),
        clean.replace("＋", "+"),
        clean.replace(" ", ""),
    ]
    for value in variants:
        if value and value not in candidates:
            candidates.append(value)
    return candidates


def build_page_url(page_name: str) -> str:
    return SOURCE_BASE_URL + quote(page_name, safe="")


def _heading_level(node) -> Optional[int]:
    tag = node.tag.lower() if isinstance(node.tag, str) else ""
    if len(tag) == 2 and tag.startswith("h") and tag[1].isdigit():
        return int(tag[1])
    return None


def _find_acquisition_heading(root, equipment_name: str):
    for heading in root.xpath("//h2|//h3|//h4|//h5|//h6"):
        text = re.sub(r"\s+", "", node_text(heading))
        canonical = canonical_acquisition_heading(equipment_name, text)
        if _HEADING_RE.fullmatch(canonical):
            return heading
    return None


def _find_fallback_headings(root) -> List:
    result = []
    for heading in root.xpath("//h2|//h3|//h4|//h5|//h6"):
        text = re.sub(r"\s+", "", node_text(heading))
        if _FALLBACK_HEADING_RE.fullmatch(text):
            result.append(heading)
    return result


def _section_nodes(heading) -> Iterable:
    level = _heading_level(heading) or 6
    current = heading.getnext()
    while current is not None:
        current_level = _heading_level(current)
        if current_level is not None and current_level <= level:
            break
        yield current
        current = current.getnext()


def _links_for(node) -> List[AcquisitionLink]:
    result: List[AcquisitionLink] = []
    seen = set()
    for link in node.xpath(".//a[@href]"):
        text = node_text(link)
        href = str(link.get("href") or "").strip()
        if href:
            href = urljoin(SOURCE_BASE_URL, href)
        key = (text, href)
        if not href or key in seen:
            continue
        seen.add(key)
        result.append(AcquisitionLink(text=text, href=href))
    return result


def _direct_text(node, *, exclude_tags: set[str] | None = None) -> str:
    exclude_tags = exclude_tags or {"ul", "ol", "table"}
    parts: list[str] = []
    if node.text:
        parts.append(node.text)
    for child in node:
        if isinstance(child.tag, str):
            tag = child.tag.lower()
            if tag not in exclude_tags:
                parts.extend(child.itertext())
        if child.tail:
            parts.append(child.tail)
    return normalize_text("".join(parts))


def _split_semantic_units(text: str) -> List[str]:
    """Split prose without breaking Japanese quoted quest or event titles."""

    clean = normalize_text(text)
    if not clean:
        return []
    opening = {"「": "」", "『": "』", "【": "】", "（": "）", "(": ")", "[": "]", "〈": "〉", "《": "》"}
    closing = set(opening.values())
    stack: list[str] = []
    current: list[str] = []
    result: list[str] = []

    def flush() -> None:
        value = normalize_text("".join(current))
        current.clear()
        if value:
            result.append(value)

    for char in clean:
        current.append(char)
        if char in opening:
            stack.append(opening[char])
            continue
        if char in closing:
            if stack and stack[-1] == char:
                stack.pop()
            continue
        if not stack and (char in "。！？" or char == "\n"):
            flush()
    flush()
    return result


def _resolved_context_label(text: str) -> str | None:
    clean = normalize_text(text)
    if not clean:
        return None
    resolved = resolve_acquisition_context_label(clean)
    if resolved is not None:
        return resolved
    stripped = clean.rstrip(":：")
    if stripped != clean:
        return resolve_acquisition_context_label(stripped)
    return None


def _context_method_types(text: str) -> List[str]:
    clean = normalize_text(text)
    if not clean:
        return []
    canonical = _resolved_context_label(clean) or clean
    return [value for value in classify_method_types(canonical) if value != "other"]


def _is_context_label(text: str) -> bool:
    return _resolved_context_label(text) is not None


def _is_historical_marker(text: str) -> bool:
    lines = [normalize_text(line) for line in normalize_text(text).splitlines() if normalize_text(line)]
    if not lines:
        return False
    return all(
        is_acquisition_historical_marker(line)
        or bool(_HISTORICAL_MARKER_RE.fullmatch(line))
        for line in lines
    )

def _has_acquisition_signal(text: str) -> bool:
    clean = normalize_text(text)
    if not clean:
        return False
    if _HISTORICAL_RE.search(clean) or _CURRENT_RE.search(clean):
        return True
    return any(pattern.search(clean) for _, pattern in _METHOD_PATTERNS)


def _has_explicit_acquisition_fact(text: str) -> bool:
    return bool(_EXPLICIT_ACQUISITION_FACT_RE.search(normalize_text(text)))

def classify_method_types(text: str, *, forced: Sequence[str] = ()) -> List[str]:
    compact = canonical_acquisition_classification_text(normalize_text(text))
    result = list(dict.fromkeys([
        *forced,
        *(name for name, pattern in _METHOD_PATTERNS if pattern.search(compact)),
    ]))
    return result or ["other"]


def classify_availability(text: str, inherited: str = "current-or-summary") -> str:
    clean = normalize_text(text)
    has_historical = bool(_HISTORICAL_RE.search(clean))
    has_current = bool(_CURRENT_RE.search(clean))
    if has_current and not has_historical:
        return "current"
    if has_historical and not has_current:
        return "historical"
    if has_current and has_historical:
        return "mixed-summary"
    return inherited


def _page_equipment_id(root, expected_id: int) -> Optional[int]:
    candidates: list[int] = []
    for text_node in root.xpath("//text()"):
        text = normalize_text(str(text_node))
        if "No." not in text and "no." not in text.lower():
            continue
        for match in _PAGE_ID_RE.finditer(text):
            value = int(match.group(1))
            if value not in candidates:
                candidates.append(value)
    if int(expected_id) in candidates:
        return int(expected_id)
    return candidates[0] if candidates else None


def _equipment_notes_text(root, equipment_id: int) -> Optional[str]:
    """Return the current equipment infobox's 備考 value.

    WikiWiki pages contain comparison tables, historical prose and comments
    that mention other equipment's development status. Only the current
    equipment infobox is valid evidence for this boolean.
    """

    expected = int(equipment_id)
    candidates: list[tuple[object, str]] = []
    for heading in root.xpath("//th"):
        if normalize_text("".join(heading.itertext())) != "備考":
            continue
        table = heading
        while table is not None and getattr(table, "tag", None) != "table":
            table = table.getparent()
        if table is None:
            continue

        row = heading.getparent()
        same_row_values = [
            node_text(value)
            for value in row.xpath("./td")
            if node_text(value)
        ] if row is not None else []
        if same_row_values:
            notes = " ".join(same_row_values)
        else:
            value_row = row.getnext() if row is not None else None
            notes = node_text(value_row) if value_row is not None else ""
        candidates.append((table, notes))

    # Preferred rule: the infobox itself exposes the current equipment No.
    for table, notes in candidates:
        table_ids = [
            int(match.group(1))
            for candidate in table.xpath(".//th")[:3]
            for match in _PAGE_ID_RE.finditer(node_text(candidate))
        ]
        if expected in table_ids:
            return notes

    # Compatibility for older/synthetic snapshots: accept the only 備考 row
    # only when the page-level No. still matches the requested equipment.
    if len(candidates) == 1 and _page_equipment_id(root, expected) == expected:
        return candidates[0][1]
    return None


def _development_flag(
    root,
    equipment_id: int,
) -> tuple[Optional[bool], dict]:
    notes = _equipment_notes_text(root, equipment_id)
    if notes is None:
        return None, {
            "status": "unresolved",
            "reason": "equipment-infobox-missing",
        }
    if "開発不可" in notes:
        return False, {
            "status": "resolved",
            "method": "wikiwiki-equipment-infobox-notes",
            "marker": "開発不可",
            "rawText": notes,
        }
    marker_match = re.search(r"開発(?:実装|解禁)日|開発可(?:能)?", notes)
    if marker_match:
        return True, {
            "status": "resolved",
            "method": "wikiwiki-equipment-infobox-notes",
            "marker": marker_match.group(0),
            "rawText": notes,
        }
    # In this infobox, development-capable equipment is explicitly marked.
    # A present 備考 row without such a marker therefore means unavailable.
    return False, {
        "status": "resolved",
        "method": "wikiwiki-equipment-infobox-marker-absence",
        "marker": "no-development-marker",
        "rawText": notes,
    }


def _catalog_id_from_anchor(anchor) -> tuple[int | None, str | None]:
    candidates: list[str] = []
    candidates.extend([
        str(anchor.get("title") or ""),
        str(anchor.get("aria-label") or ""),
        _direct_text(anchor, exclude_tags=set()),
    ])
    for image in anchor.xpath(".//img"):
        candidates.extend([
            str(image.get("alt") or ""),
            str(image.get("title") or ""),
            str(image.get("src") or ""),
            str(image.get("data-src") or ""),
        ])
    for candidate in candidates:
        match = _CATALOG_LABEL_RE.search(candidate)
        if match:
            return int(match.group(1)), normalize_text(match.group(2))
        match = _CATALOG_IMAGE_RE.search(candidate)
        if match:
            return int(match.group(1)), None
    return None, None


def parse_equipment_catalog_page(
    html: str,
    *,
    source_url: str = CATALOG_URL,
) -> tuple[List[EquipmentCatalogEntry], List[AcquisitionIssue]]:
    root = etree.HTML(html)
    if root is None:
        raise ValueError("WikiWiki equipment catalog could not be parsed as HTML")

    entries: dict[int, EquipmentCatalogEntry] = {}
    issues: List[AcquisitionIssue] = []
    for anchor in root.xpath("//a[@href]"):
        equipment_id, label_name = _catalog_id_from_anchor(anchor)
        if equipment_id is None:
            continue
        href = urljoin(source_url, str(anchor.get("href") or ""))
        parsed = urlparse(href)
        if parsed.netloc != "wikiwiki.jp" or not parsed.path.startswith("/kancolle/"):
            continue
        page_name = unquote(parsed.path.split("/kancolle/", 1)[1]).strip("/")
        if not page_name:
            continue
        equipment_name = label_name or page_name
        entry = EquipmentCatalogEntry(
            equipment_id=equipment_id,
            equipment_name=equipment_name,
            page_name=page_name,
            source_url=href,
        )
        previous = entries.get(equipment_id)
        if previous and previous.source_url != entry.source_url:
            issues.append(AcquisitionIssue(
                kind="duplicate-catalog-equipment-id",
                message="equipment catalog maps one ID to multiple pages",
                evidence={
                    "equipmentId": equipment_id,
                    "first": previous.to_json(),
                    "second": entry.to_json(),
                },
            ))
            continue
        entries[equipment_id] = entry

    if not entries:
        issues.append(AcquisitionIssue(
            kind="empty-equipment-catalog",
            message="equipment catalog exposed no equipment detail links",
        ))
    return [entries[key] for key in sorted(entries)], issues


_STRUCTURAL_TAGS = {"ul", "ol", "table", "div"}
_SKIP_CONTAINER_CLASSES = {
    "fold-summary",
    "caption-flybox",
    "default-advertisement",
    "pc-caption-ad-container",
}


def _merge_types(*groups: Sequence[str]) -> List[str]:
    return list(dict.fromkeys(value for group in groups for value in group if value and value != "other"))


def _link_context_types(text: str, links: Sequence[AcquisitionLink]) -> List[str]:
    """Infer only high-confidence source types from explicit source links."""

    clean = normalize_text(text)
    if "報酬" not in clean:
        return []
    for link in links:
        parsed = urlparse(link.href)
        path = unquote(parsed.path)
        if path.startswith("/kancolle/任務"):
            return ["quest"]
    return []


def _append_method(
    methods: List[AcquisitionMethod],
    seen: set[tuple],
    *,
    text: str,
    availability: str,
    evidence_kind: str,
    links: Sequence[AcquisitionLink] = (),
    forced_types: Sequence[str] = (),
    context: str | None = None,
    split_units: bool = True,
    require_classified: bool = False,
) -> None:
    normalized_text = normalize_text(text)
    if not normalized_text or is_ignored_acquisition_text(normalized_text):
        return
    units = _split_semantic_units(normalized_text) if split_units else [normalized_text]
    for unit in units:
        if not unit or _is_historical_marker(unit) or is_ignored_acquisition_text(unit):
            continue
        unit_availability = classify_availability(unit, availability)
        types = _merge_types(
            classify_method_types(unit, forced=forced_types),
            _link_context_types(unit, links),
        ) or ["other"]
        if require_classified and types == ["other"]:
            continue
        key = (unit, unit_availability, tuple(types), context)
        if key in seen:
            continue
        seen.add(key)
        methods.append(AcquisitionMethod(
            types=types,
            availability=unit_availability,
            raw_text=unit,
            links=list(links),
            evidence_kind=evidence_kind,
            context=context,
        ))


def _class_tokens(node) -> set[str]:
    return {part for part in str(node.get("class") or "").split() if part}


def _skip_container(node) -> bool:
    return bool(_class_tokens(node) & _SKIP_CONTAINER_CLASSES)


def _is_fold_container(node) -> bool:
    return "fold-container" in _class_tokens(node)


def _fold_parts(node):
    summaries = node.xpath(
        "./div[contains(concat(' ', normalize-space(@class), ' '), ' fold-summary ')]"
    )
    contents = node.xpath(
        "./div[contains(concat(' ', normalize-space(@class), ' '), ' fold-content ')]"
    )
    return (summaries[0] if summaries else None, contents[0] if contents else None)


def _table_rows(table) -> Iterable:
    rows = table.xpath("./tr|./thead/tr|./tbody/tr|./tfoot/tr")
    return rows or table.xpath(".//tr")


def _extract_table_methods(
    table,
    methods: List[AcquisitionMethod],
    seen: set[tuple],
    *,
    availability: str,
    forced_types: Sequence[str],
    context: str | None,
    require_signal: bool,
) -> None:
    rows = list(_table_rows(table))
    table_types = list(forced_types)
    table_context = context
    for row in rows:
        cells = row.xpath("./th|./td")
        if not cells:
            continue
        header = " | ".join(value for value in (node_text(cell) for cell in cells) if value)
        header_types = _context_method_types(header)
        if header_types:
            table_types = _merge_types(table_types, header_types)
            table_context = header
            break

    for row in rows:
        cells = row.xpath("./th|./td")
        if not cells or all(
            (cell.tag.lower() if isinstance(cell.tag, str) else "") == "th"
            for cell in cells
        ):
            continue
        values = [node_text(cell) for cell in cells]
        raw = " | ".join(value for value in values if value)
        if not raw or _is_context_label(raw):
            continue
        _append_method(
            methods,
            seen,
            text=raw,
            availability=availability,
            evidence_kind="table-row",
            links=_links_for(row),
            forced_types=table_types,
            context=table_context,
            split_units=False,
            require_classified=require_signal and not table_types,
        )


def _extract_list_methods(
    list_node,
    methods: List[AcquisitionMethod],
    seen: set[tuple],
    *,
    availability: str,
    forced_types: Sequence[str],
    context: str | None,
    require_signal: bool = False,
) -> None:
    list_availability = availability
    list_types = list(forced_types)
    list_context = context

    for item in list_node.xpath("./li"):
        direct = _direct_text(item, exclude_tags=_STRUCTURAL_TAGS)
        item_availability = classify_availability(direct, list_availability)
        marker = _is_historical_marker(direct)
        if marker:
            item_availability = "historical"

        label_types = _context_method_types(direct)
        has_structural_children = any(
            isinstance(child.tag, str) and child.tag.lower() in _STRUCTURAL_TAGS
            for child in item
        )
        is_label = has_structural_children and _is_context_label(direct)
        active_types = _merge_types(list_types, label_types if not is_label else ())
        child_types = label_types if is_label else list(list_types)
        child_context = direct if is_label else list_context
        emitted = False

        if direct and not marker and not is_label:
            if not require_signal or active_types or _has_acquisition_signal(direct):
                before = len(methods)
                _append_method(
                    methods,
                    seen,
                    text=direct,
                    availability=item_availability,
                    evidence_kind="list-item",
                    links=_links_for(item),
                    forced_types=active_types,
                    context=list_context,
                    split_units=require_signal,
                    require_classified=require_signal and not active_types,
                )
                emitted = len(methods) > before

        for child in item:
            tag = child.tag.lower() if isinstance(child.tag, str) else ""
            if tag in {"ul", "ol"}:
                # Nested lists below a concrete quest/ranking/event entry are
                # usually requirements or selection advice rather than another
                # acquisition record.  Label nodes, however, intentionally
                # introduce the list of concrete entries below them.
                if emitted and not is_label and set(child_types) & {"quest", "ranking", "event"}:
                    continue
                _extract_list_methods(
                    child,
                    methods,
                    seen,
                    availability=item_availability,
                    forced_types=child_types,
                    context=child_context,
                    require_signal=require_signal or (emitted and not is_label),
                )
            elif tag == "table":
                _extract_table_methods(
                    child,
                    methods,
                    seen,
                    availability=item_availability,
                    forced_types=child_types,
                    context=child_context,
                    require_signal=require_signal,
                )
            elif tag == "div" and not _skip_container(child):
                _extract_container_methods(
                    child,
                    methods,
                    seen,
                    availability=item_availability,
                    forced_types=child_types,
                    context=child_context,
                    require_signal=require_signal,
                )

        # WikiWiki often uses a flat list item as an introduction for the
        # following sibling entries (for example "任務報酬：以下...").  Keep
        # that context within this list, but never let it leak outside it.
        if marker:
            list_availability = "historical"
        elif label_types and is_label:
            list_types = label_types
            list_context = direct or list_context


def _extract_container_methods(
    container,
    methods: List[AcquisitionMethod],
    seen: set[tuple],
    *,
    availability: str,
    forced_types: Sequence[str],
    context: str | None,
    require_signal: bool,
) -> None:
    if _is_fold_container(container):
        summary, content = _fold_parts(container)
        if content is None:
            return
        summary_text = node_text(summary) if summary is not None else ""
        fold_availability = classify_availability(summary_text, availability)
        if _is_historical_marker(summary_text) or _HISTORICAL_RE.search(summary_text):
            fold_availability = "historical"
        summary_types = _context_method_types(summary_text)
        _extract_container_methods(
            content,
            methods,
            seen,
            availability=fold_availability,
            forced_types=summary_types or forced_types,
            context=summary_text or context,
            require_signal=require_signal,
        )
        return

    active_availability = availability
    active_types = list(forced_types)
    active_context = context

    for child in container:
        tag = child.tag.lower() if isinstance(child.tag, str) else ""
        if tag in {"script", "style", "button", "noscript"}:
            continue
        if tag == "div" and _is_fold_container(child):
            summary, content = _fold_parts(child)
            if content is None:
                continue
            summary_text = node_text(summary) if summary is not None else ""
            fold_availability = classify_availability(summary_text, active_availability)
            if _is_historical_marker(summary_text) or _HISTORICAL_RE.search(summary_text):
                fold_availability = "historical"
            summary_types = _context_method_types(summary_text)
            _extract_container_methods(
                content,
                methods,
                seen,
                availability=fold_availability,
                forced_types=summary_types or active_types,
                context=summary_text or active_context,
                require_signal=require_signal,
            )
            continue
        if tag == "div" and _skip_container(child):
            continue
        level = _heading_level(child)
        if level is not None:
            heading_text = node_text(child)
            active_availability = classify_availability(heading_text, active_availability)
            active_types = _context_method_types(heading_text)
            active_context = heading_text or active_context
            continue
        if tag in {"ul", "ol"}:
            _extract_list_methods(
                child,
                methods,
                seen,
                availability=active_availability,
                forced_types=active_types,
                context=active_context,
                require_signal=require_signal,
            )
            next_sibling = child.getnext()
            next_is_table = bool(
                next_sibling is not None
                and isinstance(next_sibling.tag, str)
                and next_sibling.tag.lower() == "table"
            )
            if next_is_table and _TABLE_SHIP_CONTEXT_RE.search(node_text(child)):
                active_types = ["ship"]
                active_context = "initial-equipment-ships"
            elif next_is_table:
                direct_items = child.xpath("./li")
                if direct_items:
                    last_direct = _direct_text(direct_items[-1], exclude_tags=_STRUCTURAL_TAGS)
                    pending_types = _context_method_types(last_direct)
                    if pending_types and (
                        _is_context_label(last_direct)
                        or bool(re.search(r"(?:海域|イベント).*(?:突破|報酬)", last_direct))
                    ):
                        active_types = pending_types
                        active_context = last_direct
            continue
        if tag == "table":
            _extract_table_methods(
                child,
                methods,
                seen,
                availability=active_availability,
                forced_types=active_types,
                context=active_context,
                require_signal=require_signal,
            )
            # Context introduced specifically for one following table must
            # not classify later sibling lists or historical folds.
            if active_context == "initial-equipment-ships" or (
                active_context and re.search(r"(?:海域|イベント).*(?:突破|報酬)", active_context)
            ):
                active_types = list(forced_types)
                active_context = context
            continue
        if tag == "div":
            _extract_container_methods(
                child,
                methods,
                seen,
                availability=active_availability,
                forced_types=active_types,
                context=active_context,
                require_signal=require_signal,
            )
            continue
        if tag not in {"p", "blockquote", "li"}:
            continue

        direct = _direct_text(child, exclude_tags=_STRUCTURAL_TAGS)
        if not direct:
            continue
        if _is_historical_marker(direct):
            active_availability = "historical"
            continue
        label_types = _context_method_types(direct)
        if _is_context_label(direct):
            active_types = label_types
            active_context = direct
            continue
        _append_method(
            methods,
            seen,
            text=direct,
            availability=active_availability,
            evidence_kind="paragraph",
            links=_links_for(child),
            forced_types=_merge_types(active_types, label_types),
            context=active_context,
            require_classified=require_signal and not active_types and not label_types,
        )


def _normalized_lookup_name(value: str) -> str:
    import unicodedata

    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", normalize_text(value))).casefold()


def _extract_summary_table_methods(
    root,
    *,
    equipment_name: str,
    methods: List[AcquisitionMethod],
    seen: set[tuple],
) -> None:
    expected = _normalized_lookup_name(equipment_name)
    for table in root.xpath("//table"):
        rows = list(_table_rows(table))
        if not rows:
            continue
        acquisition_column: int | None = None
        for row in rows:
            cells = row.xpath("./th|./td")
            values = [node_text(cell) for cell in cells]
            for index, value in enumerate(values):
                if "入手方法" in value:
                    acquisition_column = index
                    break
            if acquisition_column is not None:
                break
        if acquisition_column is None:
            continue
        for row in rows:
            cells = row.xpath("./th|./td")
            if acquisition_column >= len(cells):
                continue
            values = [node_text(cell) for cell in cells]
            if not any(_normalized_lookup_name(value) == expected for value in values):
                continue
            raw = values[acquisition_column]
            if not raw or raw == "入手方法":
                continue
            canonical_raw = canonical_acquisition_classification_text(raw).strip()
            forced_types = ("improvement",) if canonical_raw in {"改修", "改修更新"} else ()
            _append_method(
                methods,
                seen,
                text=raw,
                availability="current-or-summary",
                evidence_kind="summary-table-cell",
                links=_links_for(cells[acquisition_column]),
                forced_types=forced_types,
                context="comparison-table",
                split_units=False,
                require_classified=True,
            )


def _extract_fallback_methods(root, *, equipment_name: str) -> List[AcquisitionMethod]:
    """Extract only high-signal evidence outside a dedicated acquisition section.

    The general ``ゲームにおいて`` section contains extensive operational and
    historical prose. Fallback parsing therefore stays deliberately shallow.
    One exception is a nested list item that itself states a concrete acquisition
    fact (for example ``任務...報酬として入手できる``); this is a stable page
    structure, not an equipment-specific rule.
    """

    methods: List[AcquisitionMethod] = []
    seen: set[tuple] = set()
    _extract_summary_table_methods(
        root,
        equipment_name=equipment_name,
        methods=methods,
        seen=seen,
    )
    for heading in _find_fallback_headings(root):
        heading_text = node_text(heading)
        for block in _section_nodes(heading):
            if _heading_level(block) is not None:
                break
            tag = block.tag.lower() if isinstance(block.tag, str) else ""
            if tag in {"ul", "ol"}:
                for item in block.xpath("./li"):
                    direct = _direct_text(item, exclude_tags=_STRUCTURAL_TAGS)
                    if not direct:
                        continue
                    label_types = _context_method_types(direct)
                    is_label = _is_context_label(direct)
                    if is_label:
                        for child in item:
                            child_tag = child.tag.lower() if isinstance(child.tag, str) else ""
                            if child_tag in {"ul", "ol"}:
                                _extract_list_methods(
                                    child,
                                    methods,
                                    seen,
                                    availability="current-or-summary",
                                    forced_types=label_types,
                                    context=direct,
                                    require_signal=True,
                                )
                            elif child_tag == "table":
                                _extract_table_methods(
                                    child,
                                    methods,
                                    seen,
                                    availability="current-or-summary",
                                    forced_types=label_types,
                                    context=direct,
                                    require_signal=True,
                                )
                        continue
                    if _has_acquisition_signal(direct):
                        _append_method(
                            methods,
                            seen,
                            text=direct,
                            availability="current-or-summary",
                            evidence_kind="page-fallback",
                            links=_links_for(item),
                            context=heading_text,
                            require_classified=True,
                        )
                    for nested in item.xpath(".//li"):
                        nested_direct = _direct_text(nested, exclude_tags=_STRUCTURAL_TAGS)
                        if not nested_direct or not _has_explicit_acquisition_fact(nested_direct):
                            continue
                        _append_method(
                            methods,
                            seen,
                            text=nested_direct,
                            availability="current-or-summary",
                            evidence_kind="nested-page-fallback",
                            links=_links_for(nested),
                            context=heading_text,
                            require_classified=True,
                        )
                continue
            if tag not in {"p", "blockquote"}:
                continue
            direct = _direct_text(block, exclude_tags=_STRUCTURAL_TAGS)
            if not direct or not _has_acquisition_signal(direct):
                continue
            _append_method(
                methods,
                seen,
                text=direct,
                availability="current-or-summary",
                evidence_kind="page-fallback",
                links=_links_for(block),
                context=heading_text,
                require_classified=True,
            )
    return methods


def _extract_section_methods(nodes: List) -> List[AcquisitionMethod]:
    methods: List[AcquisitionMethod] = []
    seen: set[tuple] = set()
    wrapper = etree.Element("div")
    for node in nodes:
        # Never detach evidence nodes from the parsed page.  Later source
        # projections still need the original DOM (notably the development
        # availability flag in the equipment infobox).
        wrapper.append(copy.deepcopy(node))
    _extract_container_methods(
        wrapper,
        methods,
        seen,
        availability="current-or-summary",
        forced_types=(),
        context=None,
        require_signal=False,
    )
    return methods

def parse_equipment_acquisition_page(
    html: str,
    *,
    equipment_id: int,
    equipment_name: str,
    source_url: str,
) -> tuple[dict, List[AcquisitionIssue]]:
    root = etree.HTML(html)
    issues: List[AcquisitionIssue] = []
    if root is None:
        raise ValueError("WikiWiki equipment page could not be parsed as HTML")

    development_available, development_resolution = _development_flag(
        root, int(equipment_id)
    )
    if development_available is None:
        issues.append(AcquisitionIssue(
            kind="development-flag-unresolved",
            message="WikiWiki equipment infobox did not resolve a boolean development flag",
            evidence=development_resolution,
        ))

    page_equipment_id = _page_equipment_id(root, int(equipment_id))
    if page_equipment_id is None:
        issues.append(AcquisitionIssue(
            kind="missing-page-equipment-id",
            message="equipment page did not expose a No. identifier",
        ))
    elif page_equipment_id != int(equipment_id):
        issues.append(AcquisitionIssue(
            kind="equipment-id-mismatch",
            message="WikiWiki page No. does not match Start2 equipment ID",
            evidence={"expected": int(equipment_id), "actual": page_equipment_id},
        ))

    heading = _find_acquisition_heading(root, equipment_name)
    evidence_scope = "acquisition-section"
    if heading is None:
        issues.append(AcquisitionIssue(
            kind="missing-acquisition-section",
            message="equipment page has no 入手方法 section",
        ))
        methods = _extract_fallback_methods(root, equipment_name=equipment_name)
        evidence_scope = "page-fallback"
        section_heading = None
    else:
        nodes = list(_section_nodes(heading))
        methods = _extract_section_methods(nodes)
        if not methods:
            methods = _extract_fallback_methods(root, equipment_name=equipment_name)
            evidence_scope = "page-fallback"
            if not methods:
                issues.append(AcquisitionIssue(
                    kind="empty-acquisition-section",
                    message="equipment page acquisition section contained no usable evidence",
                ))
        section_heading = node_text(heading)

    current_types = sorted({
        method_type
        for method in methods
        if method.availability in {"current", "current-or-summary", "mixed-summary"}
        for method_type in method.types
    })
    historical_types = sorted({
        method_type
        for method in methods
        if method.availability in {"historical", "mixed-summary"}
        for method_type in method.types
    })
    unclassified = [method for method in methods if method.types == ["other"]]
    fatal_issue_kinds = {
        "equipment-id-mismatch",
        "missing-page-equipment-id",
        "development-flag-unresolved",
    }
    accepted = not any(issue.kind in fatal_issue_kinds for issue in issues)
    if not methods:
        coverage_status = "missing-section" if heading is None else "empty-section"
    elif evidence_scope == "page-fallback":
        coverage_status = "fallback" if not unclassified else "fallback-partial"
    elif unclassified:
        coverage_status = "partial"
    else:
        coverage_status = "parsed"
    if not accepted:
        coverage_status = "rejected"

    record = {
        "equipmentId": int(equipment_id),
        "equipmentName": equipment_name,
        "source": SOURCE_ID,
        "sourceUrl": source_url,
        "pageEquipmentId": page_equipment_id,
        "sectionHeading": section_heading,
        "evidenceScope": evidence_scope,
        **(
            {"developmentAvailable": development_available}
            if isinstance(development_available, bool)
            else {}
        ),
        "developmentResolution": development_resolution,
        "currentMethodTypes": current_types,
        "historicalMethodTypes": historical_types,
        "methods": [method.to_json() for method in methods],
        "methodCount": len(methods),
        "unclassifiedEvidenceCount": len(unclassified),
        "issueCount": len(issues),
        "accepted": accepted,
        "coverageStatus": coverage_status,
        "schemaVersion": 3,
    }
    return record, issues
