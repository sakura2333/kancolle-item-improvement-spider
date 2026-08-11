from __future__ import annotations

"""WikiWiki card-list catalog parsing and name-based URL resolution.

This module is intentionally standard-library only.  Wiki display numbers are
accepted as extraction hints, but are never used to join Wiki pages to Start2
entities.  The public contract is display-name -> exact page URL.
"""

import html
import json
import re
import unicodedata
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse

SOURCE_BASE = "https://wikiwiki.jp/kancolle/"
CARD_LABEL_RE = re.compile(r"^\s*(?:No\.?\s*)?\d{1,4}\s*[:：;；]\s*(.+?)\s*$", re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")
EXCLUDED_PATH_PREFIXES = (
    "/kancolle/:",
    "/kancolle/?",
    "/kancolle/index.php",
)


def clean_display_name(value: str) -> str:
    cleaned = html.unescape(str(value)).replace("\u3000", " ")
    return SPACE_RE.sub(" ", cleaned).strip()


def normalize_name(value: str) -> str:
    """Normalize safe presentation variants without collapsing remodel names."""

    normalized = unicodedata.normalize("NFKC", clean_display_name(value))
    return SPACE_RE.sub(" ", normalized).strip()




def load_name_aliases(path: Path) -> dict[str, str | None]:
    """Load human-accepted Start2 -> Wiki display-name aliases and explicit source exclusions."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError(f"invalid WikiWiki page-name alias dictionary: {path}")
    if payload.get("reviewStatus") != "accepted":
        raise ValueError(f"WikiWiki page-name alias dictionary is not accepted: {path}")
    raw_aliases = payload.get("aliases")
    if not isinstance(raw_aliases, list):
        raise ValueError(f"WikiWiki page-name alias dictionary has no aliases: {path}")
    result: dict[str, str | None] = {}
    for index, raw in enumerate(raw_aliases, 1):
        if not isinstance(raw, dict) or raw.get("status") != "accepted":
            continue
        start2_name = clean_display_name(raw.get("start2Name", ""))
        wiki_name = clean_display_name(raw.get("wikiName", ""))
        if not start2_name or not wiki_name:
            raise ValueError(f"WikiWiki page-name alias #{index} is incomplete: {path}")
        if start2_name in result and result[start2_name] != wiki_name:
            raise ValueError(f"conflicting WikiWiki page-name alias for {start2_name!r}")
        result[start2_name] = wiki_name

    raw_exclusions = payload.get("exclusions", [])
    if not isinstance(raw_exclusions, list):
        raise ValueError(f"WikiWiki page-name alias dictionary has invalid exclusions: {path}")
    for index, raw in enumerate(raw_exclusions, 1):
        if not isinstance(raw, dict) or raw.get("status") != "accepted":
            continue
        start2_name = clean_display_name(raw.get("start2Name", ""))
        reason = clean_display_name(raw.get("reason", ""))
        if not start2_name or not reason:
            raise ValueError(f"WikiWiki page-name exclusion #{index} is incomplete: {path}")
        if start2_name in result and result[start2_name] is not None:
            raise ValueError(f"WikiWiki page-name exclusion conflicts with alias for {start2_name!r}")
        result[start2_name] = None
    return result

def card_name(value: str) -> str | None:
    candidate = clean_display_name(value)
    match = CARD_LABEL_RE.match(candidate)
    if not match:
        return None
    name = match.group(1).strip()
    return name or None


def canonical_page_url(href: str, *, source_url: str = SOURCE_BASE) -> str | None:
    href = html.unescape(str(href or "")).strip()
    if not href or href.startswith(("#", "javascript:", "mailto:")):
        return None
    absolute = urljoin(source_url, href)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or parsed.netloc != "wikiwiki.jp":
        return None
    if not parsed.path.startswith("/kancolle/"):
        return None
    if parsed.path.startswith(EXCLUDED_PATH_PREFIXES):
        return None
    page_name = unquote(parsed.path[len("/kancolle/") :]).strip("/")
    if not page_name or page_name in {"装備カード一覧", "艦娘カード一覧"}:
        return None
    return SOURCE_BASE + quote(page_name, safe="")


def page_name_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.netloc != "wikiwiki.jp" or not parsed.path.startswith("/kancolle/"):
        return None
    name = unquote(parsed.path[len("/kancolle/") :]).strip("/")
    return clean_display_name(name) or None


class CardListParser(HTMLParser):
    def __init__(self, *, source_url: str):
        super().__init__(convert_charrefs=True)
        self.source_url = source_url
        self._anchor: dict[str, Any] | None = None
        self.candidates: list[dict[str, str]] = []
        self.anchor_count = 0
        self.card_image_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "a":
            self.anchor_count += 1
            labels = []
            for key in ("title", "aria-label"):
                if name := card_name(values.get(key, "")):
                    labels.append(name)
            self._anchor = {"href": values.get("href", ""), "texts": [], "labels": labels}
            return
        if tag == "img":
            labels = [values.get("alt", ""), values.get("title", "")]
            parsed = [name for label in labels if (name := card_name(label))]
            if parsed:
                self.card_image_count += 1
                if self._anchor is not None:
                    self._anchor["labels"].extend(parsed)
                else:
                    for name in parsed:
                        self.candidates.append({"wikiName": name, "href": ""})

    def handle_data(self, data: str) -> None:
        if self._anchor is not None and data.strip():
            self._anchor["texts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._anchor is None:
            return
        anchor = self._anchor
        self._anchor = None
        labels = list(anchor["labels"])
        text_name = card_name("".join(anchor["texts"]))
        if text_name:
            labels.append(text_name)
        for name in labels:
            self.candidates.append({"wikiName": name, "href": str(anchor["href"])})


def parse_card_catalog(html_text: str, *, kind: str, source_url: str) -> dict[str, Any]:
    if kind not in {"equipment", "ship"}:
        raise ValueError(f"unsupported catalog kind: {kind}")
    parser = CardListParser(source_url=source_url)
    parser.feed(html_text)

    entries: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    invalid = 0
    fallback_urls = 0
    for candidate in parser.candidates:
        label_name = clean_display_name(candidate["wikiName"])
        url = canonical_page_url(candidate.get("href", ""), source_url=source_url)
        source = "card-list-link"
        wiki_name = page_name_from_url(url) if url is not None else None
        if url is None:
            # The card label itself is Wiki-authored and therefore preserves
            # full-width punctuation that Start2 may not.  This is a fallback
            # from exact Wiki display name, not a Start2-name guess.
            wiki_name = label_name
            url = SOURCE_BASE + quote(wiki_name, safe="")
            source = "card-list-display-name"
            fallback_urls += 1
        elif not wiki_name:
            wiki_name = label_name
        if not wiki_name or not url.startswith(SOURCE_BASE):
            invalid += 1
            continue
        key = (wiki_name, url)
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            "wikiName": wiki_name,
            "normalizedName": normalize_name(wiki_name),
            "url": url,
            "urlSource": source,
        })

    entries.sort(key=lambda item: (item["normalizedName"], item["wikiName"], item["url"]))
    normalized_groups: dict[str, int] = defaultdict(int)
    for entry in entries:
        normalized_groups[entry["normalizedName"]] += 1
    ambiguous_names = sorted(name for name, count in normalized_groups.items() if count > 1)
    return {
        "schemaVersion": 1,
        "kind": kind,
        "sourceUrl": source_url,
        "joinKey": "normalized-name",
        "entries": entries,
        "diagnostics": {
            "anchors": parser.anchor_count,
            "cardImages": parser.card_image_count,
            "candidates": len(parser.candidates),
            "entries": len(entries),
            "invalid": invalid,
            "displayNameUrlFallbacks": fallback_urls,
            "ambiguousNormalizedNames": ambiguous_names,
        },
    }


def catalog_indexes(catalog: dict[str, Any]) -> tuple[dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]]:
    exact: dict[str, list[dict[str, str]]] = defaultdict(list)
    normalized: dict[str, list[dict[str, str]]] = defaultdict(list)
    for raw in catalog.get("entries", []):
        if not isinstance(raw, dict):
            continue
        wiki_name = str(raw.get("wikiName") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not wiki_name or not url.startswith(SOURCE_BASE):
            continue
        entry = {
            "wikiName": wiki_name,
            "normalizedName": normalize_name(wiki_name),
            "url": url,
            "urlSource": str(raw.get("urlSource") or "card-list"),
        }
        exact[wiki_name].append(entry)
        normalized[entry["normalizedName"]].append(entry)
    return dict(exact), dict(normalized)


def resolve_name(
    name: str,
    catalog: dict[str, Any],
    *,
    aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    exact, normalized = catalog_indexes(catalog)
    if name in exact:
        candidates = exact[name]
        match_type = "exact-name"
    else:
        candidates = normalized.get(normalize_name(name), [])
        match_type = "normalized-name"

    if not candidates and aliases and name in aliases:
        alias_name = aliases[name]
        if alias_name is None:
            return {
                "status": "excluded",
                "matchType": "accepted-name-exclusion",
                "candidates": [],
            }
        candidates = exact.get(alias_name, [])
        if not candidates:
            candidates = normalized.get(normalize_name(alias_name), [])
        if not candidates:
            candidates = [{
                "wikiName": alias_name,
                "normalizedName": normalize_name(alias_name),
                "url": SOURCE_BASE + quote(alias_name, safe=""),
                "urlSource": "accepted-name-alias",
            }]
            match_type = "accepted-name-alias-direct"
        else:
            match_type = "accepted-name-alias"

    unique = {(entry["wikiName"], entry["url"]): entry for entry in candidates}
    values = list(unique.values())
    if len(values) == 1:
        entry = values[0]
        return {"status": "resolved", "matchType": match_type, **entry}
    if values:
        return {"status": "ambiguous", "matchType": match_type, "candidates": values}
    return {"status": "unresolved", "matchType": "none", "candidates": []}
