from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from util.start2.start2_item_utils import Start2ItemUtils
from util.start2.start2_ship_utils import Start2ShipUtils
from util.text_utils import normalize_name

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "source-semantic-aliases.json"
SUPPORTED_ENTITY_TYPES = {"ship", "equipment"}
SUPPORTED_MATCH_MODES = {"normalized-full-cell-exact", "normalized-alias-exact"}


class SemanticAliasError(ValueError):
    pass


@dataclass(frozen=True)
class SemanticAlias:
    alias_id: str
    source: str
    entity_type: str
    match_mode: str
    raw_variants: Tuple[str, ...]
    canonical_id: int
    canonical_name: str
    qualifier: str = ""
    required_field_contains: Mapping[str, str] = field(default_factory=dict)
    reason: str = ""


class SemanticAliasDictionary:
    def __init__(self, entries: Iterable[SemanticAlias]):
        self.entries = tuple(entries)
        self._by_key: Dict[Tuple[str, str, str], SemanticAlias] = {}
        for entry in self.entries:
            for raw in entry.raw_variants:
                key = (entry.source, entry.entity_type, normalize_name(raw))
                if not key[2]:
                    raise SemanticAliasError(f"semantic alias {entry.alias_id} has an empty variant")
                previous = self._by_key.get(key)
                if previous and previous.canonical_id != entry.canonical_id:
                    raise SemanticAliasError(
                        f"semantic alias collision for {entry.source}/{entry.entity_type}/{raw!r}: "
                        f"{previous.canonical_id} != {entry.canonical_id}"
                    )
                self._by_key[key] = entry

    def lookup(
        self,
        source: str,
        entity_type: str,
        raw_text: Any,
        *,
        match_modes: Optional[Iterable[str]] = None,
    ) -> Optional[SemanticAlias]:
        key = (str(source), str(entity_type), normalize_name(str(raw_text or "")))
        entry = self._by_key.get(key)
        if entry is None or match_modes is None:
            return entry
        allowed = set(match_modes)
        return entry if entry.match_mode in allowed else None

    def validate_against_start2(
        self,
        item_utils: Start2ItemUtils,
        ship_utils: Start2ShipUtils,
    ) -> dict:
        validated = 0
        for entry in self.entries:
            if entry.entity_type == "ship":
                target = ship_utils.get_by_id(entry.canonical_id)
            elif entry.entity_type == "equipment":
                target = item_utils.find_by_id(entry.canonical_id)
            else:  # Defensive; the loader rejects this too.
                raise SemanticAliasError(
                    f"semantic alias {entry.alias_id} has unsupported entity type {entry.entity_type!r}"
                )

            if target is None:
                raise SemanticAliasError(
                    f"semantic alias {entry.alias_id} target ID {entry.canonical_id} is absent from Start2"
                )
            actual_name = str(target.get("api_name") or "")
            if normalize_name(actual_name) != normalize_name(entry.canonical_name):
                raise SemanticAliasError(
                    f"semantic alias {entry.alias_id} target name changed: "
                    f"expected {entry.canonical_name!r}, got {actual_name!r}"
                )
            for field, expected_fragment in entry.required_field_contains.items():
                actual = str(target.get(field) or "")
                if expected_fragment not in actual:
                    raise SemanticAliasError(
                        f"semantic alias {entry.alias_id} target evidence changed: "
                        f"{field} no longer contains {expected_fragment!r}"
                    )
            validated += 1
        return {"entryCount": len(self.entries), "validatedTargetCount": validated}


def _as_non_empty_text(value: Any, field: str, alias_id: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SemanticAliasError(f"semantic alias {alias_id} is missing {field}")
    return text


def _parse_entry(raw: Any) -> Optional[SemanticAlias]:
    if not isinstance(raw, dict):
        raise SemanticAliasError("semantic alias entry must be an object")
    alias_id = _as_non_empty_text(raw.get("id"), "id", "<unknown>")
    if raw.get("status") != "accepted":
        return None
    source = _as_non_empty_text(raw.get("source"), "source", alias_id)
    entity_type = _as_non_empty_text(raw.get("entityType"), "entityType", alias_id)
    if entity_type not in SUPPORTED_ENTITY_TYPES:
        raise SemanticAliasError(
            f"semantic alias {alias_id} has unsupported entity type {entity_type!r}"
        )
    match_mode = _as_non_empty_text(raw.get("matchMode"), "matchMode", alias_id)
    if match_mode not in SUPPORTED_MATCH_MODES:
        raise SemanticAliasError(
            f"semantic alias {alias_id} has unsupported match mode {match_mode!r}"
        )
    variants = raw.get("rawVariants")
    if not isinstance(variants, list) or not variants:
        raise SemanticAliasError(f"semantic alias {alias_id} must declare rawVariants")
    raw_variants = tuple(_as_non_empty_text(value, "rawVariants", alias_id) for value in variants)

    target = raw.get("target")
    if not isinstance(target, dict):
        raise SemanticAliasError(f"semantic alias {alias_id} must declare target")
    try:
        canonical_id = int(target.get("canonicalId"))
    except (TypeError, ValueError) as exc:
        raise SemanticAliasError(f"semantic alias {alias_id} has invalid canonicalId") from exc
    if canonical_id <= 0:
        raise SemanticAliasError(f"semantic alias {alias_id} has invalid canonicalId")
    canonical_name = _as_non_empty_text(target.get("canonicalName"), "canonicalName", alias_id)

    required = target.get("requiredFieldContains") or {}
    if not isinstance(required, dict):
        raise SemanticAliasError(
            f"semantic alias {alias_id} requiredFieldContains must be an object"
        )
    required_field_contains = {
        _as_non_empty_text(key, "requiredFieldContains key", alias_id):
        _as_non_empty_text(value, "requiredFieldContains value", alias_id)
        for key, value in required.items()
    }
    return SemanticAlias(
        alias_id=alias_id,
        source=source,
        entity_type=entity_type,
        match_mode=match_mode,
        raw_variants=raw_variants,
        canonical_id=canonical_id,
        canonical_name=canonical_name,
        qualifier=str(target.get("qualifier") or "").strip(),
        required_field_contains=required_field_contains,
        reason=str(raw.get("reason") or "").strip(),
    )


@lru_cache(maxsize=1)
def load_semantic_alias_dictionary() -> SemanticAliasDictionary:
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SemanticAliasError(f"cannot load semantic alias dictionary {CONFIG_PATH}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise SemanticAliasError("semantic alias dictionary schemaVersion must be 1")
    if payload.get("reviewStatus") != "accepted":
        raise SemanticAliasError("semantic alias dictionary is not human-accepted")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise SemanticAliasError("semantic alias dictionary entries must be an array")
    entries = [entry for entry in (_parse_entry(raw) for raw in raw_entries) if entry is not None]
    return SemanticAliasDictionary(entries)


def resolve_semantic_alias(
    source: str,
    entity_type: str,
    raw_text: Any,
    *,
    match_modes: Optional[Iterable[str]] = None,
) -> Optional[SemanticAlias]:
    return load_semantic_alias_dictionary().lookup(
        source, entity_type, raw_text, match_modes=match_modes
    )


def validate_semantic_alias_dictionary(
    item_utils: Start2ItemUtils,
    ship_utils: Start2ShipUtils,
) -> dict:
    return load_semantic_alias_dictionary().validate_against_start2(item_utils, ship_utils)
