from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import unquote, urlparse

from configs.path import get_data_dir
from util.start2.start2_ship_utils import Start2ShipUtils, ship_utils

QUEST_DATA_URL = (
    "https://raw.githubusercontent.com/kcwikizh/"
    "kcQuests/refs/heads/main/quests-scn.json"
)
KCWIKI_SHIP_CACHE = (
    Path(get_data_dir("raw_data"))
    / "site_cache"
    / "raw.githubusercontent.com"
    / "kcwiki"
    / "kancolle-data"
    / "refs"
    / "heads"
    / "master"
    / "wiki"
    / "ship.json"
)

_GENERIC_LINK_NAMES = {
    "任務",
    "任務一覧",
    "開発",
    "改修工廠",
    "建造",
    "ランキング",
    "イベント",
    "装備",
    "入手方法",
}
_SHIP_MARKER_ONLY_RE = re.compile(
    r"^(?:初期装備艦|持参艦|所持艦|装備艦)(?:は|を|一覧|下表|の通り|について|[:：、。\s])*$"
)
_QUEST_CODE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9]{2,12})(?![A-Za-z0-9])")

# Some ships share the same Start2 display name across distinct forms.  Keep
# direct text aliases separate from WikiWiki link-target semantics: the visible
# text may be a generic name, while the linked page name identifies the form.
# Link numbers are never used as game IDs.
AMBIGUOUS_SHIP_RULES: dict[str, dict[str, object]] = {
    "Glorious": {
        "explicitNames": {
            "Glorious(巡洋戦艦)": 1022,
            "Glorious(正規空母)": 1027,
            # Accepted presentation synonym; WikiWiki's canonical page uses 正規空母.
            "Glorious(航空母艦)": 1027,
        },
        "linkTargets": {
            # WikiWiki's base /Glorious page is the unmodified battlecruiser.
            "Glorious": 1022,
            "Glorious(巡洋戦艦)": 1022,
            "Glorious(正規空母)": 1027,
            "Glorious(航空母艦)": 1027,
        },
        "displayNames": {
            1022: "Glorious(巡洋戦艦)",
            1027: "Glorious(正規空母)",
        },
    },
}


def normalize_reference_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("’", "'").replace("`", "'")
    text = re.sub(r"[「」『』【】\[\]〈〉《》]", "", text)
    text = re.sub(r"[\s・･,，、:：;；。.!！?？\-‐‑–—~〜～_/]+", "", text)
    text = text.replace("*", "")
    return text.casefold().strip()


def normalize_exact_quest_text(value: str) -> str:
    """Normalize only presentation-level whitespace for exact quest matching.

    Quest relationships are public package data, so they must not be inferred
    from partial names or punctuation-insensitive similarity.  NFKC keeps the
    comparison stable across full-width ASCII/space variants while preserving
    all meaningful Japanese punctuation and quotes in the canonical name.
    """

    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _page_name_from_href(href: str) -> str:
    parsed = urlparse(str(href or ""))
    path = unquote(parsed.path or "")
    marker = "/kancolle/"
    if marker not in path:
        return ""
    return path.split(marker, 1)[1].strip("/")


def _dedupe_dicts(values: Iterable[dict], *, key_fields: Sequence[str]) -> list[dict]:
    result: list[dict] = []
    seen: set[tuple] = set()
    for value in values:
        key = tuple(value.get(field) for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


@dataclass(frozen=True)
class _ShipAlias:
    normalized: str
    raw_alias: str
    ship_id: int
    ship_name: str
    source: str


class ShipReferenceCatalog:
    def __init__(
        self,
        start2: Start2ShipUtils,
        *,
        kcwiki_ship_path: Path | None = KCWIKI_SHIP_CACHE,
    ) -> None:
        self.start2 = start2
        self.by_id = {
            int(ship["api_id"]): ship
            for ship in start2.ships
            if int(ship.get("api_id") or 0) > 0
            and int(ship.get("api_sortno") or 0) > 0
        }
        self.aliases: dict[str, list[_ShipAlias]] = {}
        self.ambiguous_rules: dict[str, dict[str, object]] = {}
        for ship_id, ship in self.by_id.items():
            self._add_alias(
                str(ship.get("api_name") or ""),
                ship_id,
                str(ship.get("api_name") or ""),
                "start2-name",
            )
        if kcwiki_ship_path and kcwiki_ship_path.is_file():
            payload = json.loads(kcwiki_ship_path.read_text(encoding="utf-8"))
            records = payload.values() if isinstance(payload, dict) else payload
            for record in records:
                if not isinstance(record, dict):
                    continue
                ship_id = int(record.get("_api_id") or 0)
                if ship_id not in self.by_id:
                    continue
                japanese_name = str(record.get("_japanese_name") or "").strip()
                suffix = str(record.get("_japanese_suffix") or "").strip()
                official_name = str(self.by_id[ship_id].get("api_name") or japanese_name)
                if japanese_name and suffix:
                    self._add_alias(
                        f"{japanese_name}{suffix}",
                        ship_id,
                        official_name,
                        "kcwiki-name-with-suffix",
                    )
        for base_name, rule_config in AMBIGUOUS_SHIP_RULES.items():
            normalized_base = normalize_reference_name(base_name)
            explicit_names = dict(rule_config.get("explicitNames", {}))
            link_targets = dict(rule_config.get("linkTargets", {}))
            configured_display = dict(rule_config.get("displayNames", {}))
            available_variants: dict[str, tuple[int, str]] = {}
            available_link_targets: dict[str, tuple[int, str]] = {}
            display_by_id: dict[int, str] = {}

            configured_ids = set(explicit_names.values()) | set(link_targets.values())
            for ship_id in sorted(configured_ids):
                if ship_id not in self.by_id:
                    continue
                official_name = str(self.by_id[ship_id].get("api_name") or base_name)
                if normalize_reference_name(official_name) != normalized_base:
                    raise ValueError(
                        "ambiguous ship rule conflicts with Start2: "
                        f"{base_name} -> {ship_id}:{official_name}"
                    )
                display_by_id[ship_id] = str(
                    configured_display.get(ship_id) or official_name
                )

            for explicit_name, ship_id in explicit_names.items():
                if ship_id not in display_by_id:
                    continue
                official_name = str(self.by_id[ship_id].get("api_name") or base_name)
                self._add_alias(
                    explicit_name,
                    ship_id,
                    official_name,
                    "ambiguous-ship-explicit-name",
                )
                available_variants[normalize_reference_name(explicit_name)] = (
                    ship_id,
                    explicit_name,
                )

            for page_name, ship_id in link_targets.items():
                if ship_id not in display_by_id:
                    continue
                available_link_targets[normalize_reference_name(page_name)] = (
                    ship_id,
                    page_name,
                )

            if available_variants or available_link_targets:
                self.ambiguous_rules[normalized_base] = {
                    "baseName": base_name,
                    "variants": available_variants,
                    "linkTargets": available_link_targets,
                    "displayById": display_by_id,
                }

        self.sorted_aliases = sorted(
            (
                alias
                for aliases in self.aliases.values()
                for alias in aliases
                if len(alias.normalized) >= 2
            ),
            key=lambda alias: (-len(alias.normalized), alias.normalized, alias.ship_id),
        )

    @classmethod
    def load(cls) -> "ShipReferenceCatalog":
        return cls(ship_utils.load())

    def _add_alias(self, raw_alias: str, ship_id: int, ship_name: str, source: str) -> None:
        normalized = normalize_reference_name(raw_alias)
        if not normalized:
            return
        alias = _ShipAlias(normalized, raw_alias, ship_id, ship_name, source)
        bucket = self.aliases.setdefault(normalized, [])
        if all(existing.ship_id != ship_id for existing in bucket):
            bucket.append(alias)

    def _candidate_display_names(
        self, normalized: str, matches: Sequence[_ShipAlias]
    ) -> list[str]:
        rule = self.ambiguous_rules.get(normalized)
        display_by_id = rule.get("displayById", {}) if rule else {}
        return [
            str(display_by_id.get(match.ship_id) or match.ship_name)
            for match in sorted(matches, key=lambda value: value.ship_id)
        ]

    def resolve_exact(self, raw_name: str, *, evidence: str) -> dict:
        normalized = normalize_reference_name(raw_name)
        matches = self.aliases.get(normalized, [])
        if len(matches) == 1:
            match = matches[0]
            return {
                "rawName": raw_name,
                "shipId": match.ship_id,
                "shipName": match.ship_name,
                "status": "resolved",
                "resolution": match.source,
                "evidence": evidence,
            }
        if len(matches) > 1:
            candidate_ids = sorted(match.ship_id for match in matches)
            candidate_names = self._candidate_display_names(normalized, matches)
            return {
                "rawName": raw_name,
                "shipId": None,
                "shipName": None,
                "status": "ambiguous",
                "candidateShipIds": candidate_ids,
                "candidateShipNames": candidate_names,
                "candidateShips": [
                    {"shipId": ship_id, "shipName": ship_name}
                    for ship_id, ship_name in zip(candidate_ids, candidate_names)
                ],
                "evidence": evidence,
            }
        return {
            "rawName": raw_name,
            "shipId": None,
            "shipName": None,
            "status": "unresolved",
            "evidence": evidence,
        }

    def resolve_link(self, text: str, page_name: str, *, href: str = "") -> dict | None:
        text = str(text or "").strip()
        page_name = str(page_name or "").strip()
        text_ref = self.resolve_exact(text, evidence="link-text") if text else None
        page_ref = (
            self.resolve_exact(page_name, evidence="link-page")
            if page_name
            else None
        )

        if text_ref and text_ref.get("status") == "ambiguous":
            normalized_base = normalize_reference_name(text)
            rule = self.ambiguous_rules.get(normalized_base)
            link_targets = rule.get("linkTargets", {}) if rule else {}
            target = (
                link_targets.get(normalize_reference_name(page_name))
                if page_name
                else None
            )
            if target is not None:
                ship_id, matched_page_name = target
                display_by_id = rule.get("displayById", {}) if rule else {}
                explicit_name = str(display_by_id.get(ship_id) or matched_page_name)
                if ship_id in set(text_ref.get("candidateShipIds") or []):
                    return {
                        "rawName": text,
                        "shipId": ship_id,
                        "shipName": str(self.by_id[ship_id].get("api_name") or text),
                        "status": "resolved",
                        "resolution": "ambiguous-ship-link-target",
                        "evidence": "link-cross-validation",
                        "linkTarget": page_name,
                        "linkHref": href or None,
                        "explicitShipName": explicit_name,
                        "candidateShipIds": text_ref.get("candidateShipIds", []),
                        "candidateShipNames": text_ref.get("candidateShipNames", []),
                    }
            unresolved = dict(text_ref)
            unresolved["linkTarget"] = page_name or None
            unresolved["linkHref"] = href or None
            unresolved["evidence"] = "link-cross-validation-failed"
            return unresolved

        if text_ref and text_ref.get("status") == "resolved":
            if page_ref and page_ref.get("status") == "resolved":
                if int(text_ref["shipId"]) != int(page_ref["shipId"]):
                    candidate_ids = sorted({
                        int(text_ref["shipId"]),
                        int(page_ref["shipId"]),
                    })
                    return {
                        "rawName": text,
                        "shipId": None,
                        "shipName": None,
                        "status": "ambiguous",
                        "candidateShipIds": candidate_ids,
                        "candidateShipNames": [
                            str(self.by_id[value].get("api_name") or value)
                            for value in candidate_ids
                        ],
                        "evidence": "link-target-conflict",
                        "linkTarget": page_name,
                        "linkHref": href or None,
                    }
            resolved = dict(text_ref)
            if page_name:
                resolved["linkTarget"] = page_name
            if href:
                resolved["linkHref"] = href
            return resolved

        if page_ref and page_ref.get("status") != "unresolved":
            resolved = dict(page_ref)
            if text:
                resolved["linkText"] = text
            if href:
                resolved["linkHref"] = href
            return resolved
        return None

    def scan_text(self, raw_text: str, *, evidence: str) -> list[dict]:
        normalized_text = normalize_reference_name(raw_text)
        if not normalized_text:
            return []
        selected: list[_ShipAlias] = []
        selected_norms: list[str] = []
        for alias in self.sorted_aliases:
            if alias.normalized not in normalized_text:
                continue
            if any(alias.normalized in existing for existing in selected_norms):
                continue
            selected.append(alias)
            selected_norms.append(alias.normalized)
        refs: list[dict] = []
        for normalized in selected_norms:
            aliases = self.aliases.get(normalized, [])
            raw_alias = aliases[0].raw_alias if aliases else normalized
            refs.append(self.resolve_exact(raw_alias, evidence=evidence))
        return _dedupe_dicts(
            refs,
            key_fields=("status", "shipId", "rawName", "evidence"),
        )


@dataclass(frozen=True)
class _QuestAlias:
    normalized: str
    raw_alias: str
    quest_key: int
    quest_code: str
    quest_name: str


class QuestReferenceCatalog:
    """Canonical quest catalog keyed by kcQuests' top-level numeric key."""

    def __init__(self, records: Sequence[dict]) -> None:
        self.records = [record for record in records if isinstance(record, dict)]
        self.by_code: dict[str, list[_QuestAlias]] = {}
        self.by_name: dict[str, list[_QuestAlias]] = {}
        for record in self.records:
            quest_key = int(record.get("questKey") or 0)
            quest_code = str(record.get("code") or "").strip()
            quest_name = str(record.get("name") or "").strip()
            if quest_key <= 0:
                continue
            if quest_name:
                alias = _QuestAlias(
                    normalize_exact_quest_text(quest_name),
                    quest_name,
                    quest_key,
                    quest_code,
                    quest_name,
                )
                self.by_name.setdefault(alias.normalized, []).append(alias)
            if quest_code:
                code_alias = _QuestAlias(
                    quest_code.casefold(), quest_code, quest_key, quest_code, quest_name
                )
                self.by_code.setdefault(quest_code.casefold(), []).append(code_alias)
        self.sorted_names = sorted(
            (key for key in self.by_name if len(key) >= 2),
            key=lambda value: (-len(value), value),
        )

    @classmethod
    def from_json_text(cls, raw: str) -> "QuestReferenceCatalog":
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("kcQuests catalog must be an object keyed by numeric questKey")
        records: list[dict] = []
        for raw_key, value in payload.items():
            if not str(raw_key).isdigit() or int(raw_key) <= 0:
                raise ValueError(f"kcQuests contains a non-numeric questKey: {raw_key!r}")
            if not isinstance(value, dict):
                raise ValueError(f"kcQuests questKey {raw_key} is not an object")
            records.append({**value, "questKey": int(raw_key)})
        return cls(records)

    @classmethod
    def empty(cls) -> "QuestReferenceCatalog":
        return cls([])

    def _resolved(self, alias: _QuestAlias, raw_name: str, evidence: str, status: str) -> dict:
        return {
            "rawName": raw_name,
            "questKey": alias.quest_key,
            "questCode": alias.quest_code or None,
            "questName": alias.quest_name or None,
            "status": status,
            "evidence": evidence,
        }

    def _ambiguous(self, aliases: Sequence[_QuestAlias], raw_name: str, evidence: str) -> dict:
        return {
            "rawName": raw_name,
            "questKey": None,
            "questCode": None,
            "questName": None,
            "status": "ambiguous",
            "candidateQuestKeys": sorted({alias.quest_key for alias in aliases}),
            "candidateQuestCodes": sorted({alias.quest_code for alias in aliases if alias.quest_code}),
            "candidateQuestNames": sorted({alias.quest_name for alias in aliases if alias.quest_name}),
            "evidence": evidence,
        }

    def resolve_name(self, raw_name: str, *, evidence: str) -> dict:
        normalized = normalize_exact_quest_text(raw_name)
        exact = self.by_name.get(normalized, [])
        if len(exact) == 1:
            return self._resolved(exact[0], raw_name, evidence, "resolved")
        if len(exact) > 1:
            return self._ambiguous(exact, raw_name, evidence)
        return {
            "rawName": raw_name,
            "questKey": None,
            "questCode": None,
            "questName": None,
            "status": "unresolved",
            "evidence": evidence,
        }

    def resolve_code(self, quest_code: str, *, evidence: str) -> dict | None:
        aliases = self.by_code.get(str(quest_code).casefold(), [])
        if len(aliases) == 1:
            return self._resolved(aliases[0], quest_code, evidence, "resolved")
        if len(aliases) > 1:
            return self._ambiguous(aliases, quest_code, evidence)
        return None

    def scan_text(self, raw_text: str, *, evidence: str) -> list[dict]:
        refs: list[dict] = []
        text = normalize_exact_quest_text(raw_text)

        # Match canonical names as complete contiguous strings.  This handles
        # nested WikiWiki quoting such as
        #   任務「「Gotland」戦隊、進撃せよ！」報酬
        # without truncating the inner quoted quest name to "「Gotland".
        # Longer names win when one canonical name is fully contained in
        # another, preventing a shorter alias from being collected as a second
        # relationship.
        selected_spans: list[tuple[int, int]] = []
        for canonical_name in self.sorted_names:
            candidate_spans: list[tuple[int, int]] = []
            search_from = 0
            while True:
                start = text.find(canonical_name, search_from)
                if start < 0:
                    break
                end = start + len(canonical_name)
                candidate_spans.append((start, end))
                search_from = start + 1
            accepted_spans = [
                (start, end)
                for start, end in candidate_spans
                if not any(
                    start >= selected_start and end <= selected_end
                    for selected_start, selected_end in selected_spans
                )
            ]
            if not accepted_spans:
                continue
            aliases = self.by_name.get(canonical_name, [])
            if len(aliases) == 1:
                refs.append(
                    self._resolved(
                        aliases[0],
                        aliases[0].raw_alias,
                        f"{evidence}:exact-name",
                        "resolved",
                    )
                )
            elif len(aliases) > 1:
                refs.append(
                    self._ambiguous(
                        aliases,
                        canonical_name,
                        f"{evidence}:exact-name",
                    )
                )
            selected_spans.extend(accepted_spans)

        for match in _QUEST_CODE_TOKEN_RE.finditer(text):
            resolved = self.resolve_code(match.group(1), evidence=f"{evidence}:quest-code")
            if resolved:
                refs.append(resolved)
        return _dedupe_dicts(
            refs, key_fields=("status", "questKey", "questCode", "rawName")
        )


def _reference_issue(
    *,
    kind: str,
    message: str,
    record: dict,
    method_index: int,
    reference: dict | None = None,
) -> dict:
    issue = {
        "source": "wikiwiki-equipment-detail",
        "kind": kind,
        "message": message,
        "equipmentId": record.get("equipmentId"),
        "equipmentName": record.get("equipmentName"),
        "sourceUrl": record.get("sourceUrl"),
        "methodIndex": method_index,
    }
    if reference:
        issue["reference"] = reference
    return issue


def _candidate_links(method: dict) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for link in method.get("links", []):
        text = str(link.get("text") or "").strip()
        href = str(link.get("href") or "").strip()
        page_name = _page_name_from_href(href)
        key = (text, page_name, href)
        if key in seen:
            continue
        seen.add(key)
        result.append({"text": text, "pageName": page_name, "href": href})
    return result


def _candidate_link_names(method: dict) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for link in method.get("links", []):
        text = str(link.get("text") or "").strip()
        href = str(link.get("href") or "").strip()
        page_name = _page_name_from_href(href)
        for value, evidence in ((text, "link-text"), (page_name, "link-page")):
            if not value or value in _GENERIC_LINK_NAMES:
                continue
            pair = (value, evidence)
            if pair not in result:
                result.append(pair)
    return result


def resolve_record_references(
    record: dict,
    *,
    ships: ShipReferenceCatalog,
    quests: QuestReferenceCatalog,
    quest_catalog_available: bool = True,
) -> list[dict]:
    issues: list[dict] = []
    all_ship_ids: set[int] = set()
    all_quest_keys: set[int] = set()

    for method_index, method in enumerate(record.get("methods", [])):
        types = set(method.get("types") or [])
        raw_text = str(method.get("rawText") or "")
        ship_refs: list[dict] = []
        quest_refs: list[dict] = []

        if "ship" in types:
            represented_link_names: set[str] = set()
            for link in _candidate_links(method):
                link_text = str(link.get("text") or "")
                if link_text:
                    represented_link_names.add(normalize_reference_name(link_text))
                ref = ships.resolve_link(
                    link_text,
                    str(link.get("pageName") or ""),
                    href=str(link.get("href") or ""),
                )
                if ref is not None and ref.get("status") != "unresolved":
                    ship_refs.append(ref)
            for ref in ships.scan_text(raw_text, evidence="method-text"):
                if normalize_reference_name(str(ref.get("rawName") or "")) in represented_link_names:
                    continue
                ship_refs.append(ref)
            ship_refs = _dedupe_dicts(
                ship_refs,
                key_fields=("status", "shipId", "rawName", "evidence"),
            )
            # A method can state only a generic source such as "初期装備" or
            # "多くの空母が持参".  Absence of one concrete ship name is not an
            # unresolved entity reference.  Emit diagnostics only for concrete
            # candidates that the catalog actually discovered (for example an
            # ambiguous known name), never for the whole prose sentence.
            for ref in ship_refs:
                if ref.get("shipId"):
                    all_ship_ids.add(int(ref["shipId"]))
                if ref.get("status") in {"ambiguous", "unresolved"}:
                    issues.append(_reference_issue(
                        kind=f"ship-reference-{ref['status']}",
                        message="ship reference could not be mapped to one Start2 ship ID",
                        record=record,
                        method_index=method_index,
                        reference=ref,
                    ))
            if ship_refs:
                method["shipReferences"] = ship_refs

        if "quest" in types:
            if quest_catalog_available:
                for candidate, evidence in _candidate_link_names(method):
                    ref = quests.resolve_name(candidate, evidence=evidence)
                    if ref["status"] != "unresolved":
                        quest_refs.append(ref)
                quest_refs.extend(quests.scan_text(raw_text, evidence="method-text"))
                quest_refs = _dedupe_dicts(
                    quest_refs,
                    key_fields=("status", "questKey", "questCode", "rawName"),
                )
                if not quest_refs:
                    quest_refs = [{
                        "rawName": raw_text,
                        "questKey": None,
                        "questCode": None,
                        "questName": None,
                        "status": "unresolved",
                        "evidence": "method-text",
                    }]
                for ref in quest_refs:
                    if ref.get("questKey"):
                        all_quest_keys.add(int(ref["questKey"]))
                    if ref.get("status") in {"ambiguous", "unresolved"}:
                        issues.append(_reference_issue(
                            kind=f"quest-reference-{ref['status']}",
                            message="quest reference could not be mapped to one canonical questKey",
                            record=record,
                            method_index=method_index,
                            reference=ref,
                        ))
            else:
                quest_refs = [{
                    "rawName": raw_text,
                    "questKey": None,
                    "questCode": None,
                    "questName": None,
                    "status": "catalog-unavailable",
                    "evidence": "method-text",
                }]
            method["questReferences"] = quest_refs

    record["resolvedShipIds"] = sorted(all_ship_ids)
    record["resolvedQuestKeys"] = sorted(all_quest_keys)
    record["referenceIssueCount"] = len(issues)
    record["referenceSchemaVersion"] = 2
    record["schemaVersion"] = max(int(record.get("schemaVersion") or 0), 3)
    return issues
