from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "wikiwiki-acquisition-replacements.json"
SUPPORTED_SCOPES = {
    "heading-exact",
    "context-label-exact",
    "context-label-prefix",
    "classification-literal",
    "historical-marker-exact",
    "ignore-exact",
}


class AcquisitionReplacementError(ValueError):
    pass


@dataclass(frozen=True)
class AcquisitionReplacement:
    replacement_id: str
    scope: str
    raw: str
    replacement: str
    equipment_name: str = ""
    reason: str = ""


class AcquisitionReplacementDictionary:
    def __init__(
        self,
        entries: Iterable[AcquisitionReplacement],
        *,
        classification_blacklists: Iterable[tuple[str, str]] = (),
    ):
        self.entries = tuple(entries)
        self._heading_exact: dict[tuple[str, str], str] = {}
        self._context_exact: dict[str, str] = {}
        self._context_prefix: list[tuple[str, str]] = []
        self._classification_literal: list[tuple[str, str]] = []
        self._classification_blacklist: list[tuple[str, str]] = []
        self._historical_exact: set[str] = set()
        self._ignore_exact: set[str] = set()

        for entry in self.entries:
            if entry.scope == "heading-exact":
                key = (entry.equipment_name, entry.raw)
                self._insert_unique(self._heading_exact, key, entry)
            elif entry.scope == "context-label-exact":
                self._insert_unique(self._context_exact, entry.raw, entry)
            elif entry.scope == "context-label-prefix":
                self._context_prefix.append((entry.raw, entry.replacement))
            elif entry.scope == "classification-literal":
                self._classification_literal.append((entry.raw, entry.replacement))
            elif entry.scope == "historical-marker-exact":
                self._historical_exact.add(entry.raw)
            elif entry.scope == "ignore-exact":
                self._ignore_exact.add(entry.raw)
            else:  # Defensive; the loader rejects this too.
                raise AcquisitionReplacementError(
                    f"unsupported acquisition replacement scope {entry.scope!r}"
                )

        blacklist_targets: dict[str, str] = {}
        for raw, replacement in classification_blacklists:
            previous = blacklist_targets.get(raw)
            if previous is not None and previous != replacement:
                raise AcquisitionReplacementError(
                    f"classification blacklist collision for {raw!r}: "
                    f"{previous!r} != {replacement!r}"
                )
            blacklist_targets[raw] = replacement
        self._classification_blacklist.extend(blacklist_targets.items())

        # Longest literal first prevents a short alias from consuming part of
        # a more specific accepted phrase.
        self._context_prefix.sort(key=lambda pair: (-len(pair[0]), pair[0]))
        self._classification_literal.sort(key=lambda pair: (-len(pair[0]), pair[0]))
        self._classification_blacklist.sort(key=lambda pair: (-len(pair[0]), pair[0]))

    @staticmethod
    def _insert_unique(target: dict, key: Any, entry: AcquisitionReplacement) -> None:
        previous = target.get(key)
        if previous is not None and previous != entry.replacement:
            raise AcquisitionReplacementError(
                f"acquisition replacement collision for {key!r}: "
                f"{previous!r} != {entry.replacement!r}"
            )
        target[key] = entry.replacement

    def canonical_heading(self, equipment_name: str, raw_text: str) -> str:
        return self._heading_exact.get((str(equipment_name), str(raw_text)), str(raw_text))

    def resolve_context_label(self, raw_text: str) -> Optional[str]:
        raw = str(raw_text)
        exact = self._context_exact.get(raw)
        if exact is not None:
            return exact
        for prefix, replacement in self._context_prefix:
            if raw.startswith(prefix):
                return replacement
        return None

    def is_historical_marker(self, raw_text: str) -> bool:
        return str(raw_text) in self._historical_exact

    def is_ignored(self, raw_text: str) -> bool:
        return str(raw_text) in self._ignore_exact

    def canonical_classification_text(self, raw_text: str) -> str:
        result = str(raw_text)
        for raw, replacement in self._classification_blacklist:
            result = result.replace(raw, replacement)
        for raw, replacement in self._classification_literal:
            result = result.replace(raw, replacement)
        return result


def _text(value: Any, field: str, replacement_id: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise AcquisitionReplacementError(
            f"acquisition replacement {replacement_id} is missing {field}"
        )
    return result


def _parse_entry(raw: Any) -> Optional[AcquisitionReplacement]:
    if not isinstance(raw, dict):
        raise AcquisitionReplacementError("acquisition replacement entry must be an object")
    replacement_id = _text(raw.get("id"), "id", "<unknown>")
    if raw.get("status") != "accepted":
        return None
    scope = _text(raw.get("scope"), "scope", replacement_id)
    if scope not in SUPPORTED_SCOPES:
        raise AcquisitionReplacementError(
            f"acquisition replacement {replacement_id} has unsupported scope {scope!r}"
        )
    equipment_name = str(raw.get("equipmentName") or "").strip()
    if scope == "heading-exact" and not equipment_name:
        raise AcquisitionReplacementError(
            f"acquisition replacement {replacement_id} must declare equipmentName"
        )
    return AcquisitionReplacement(
        replacement_id=replacement_id,
        scope=scope,
        raw=_text(raw.get("raw"), "raw", replacement_id),
        replacement=_text(raw.get("replacement"), "replacement", replacement_id),
        equipment_name=equipment_name,
        reason=str(raw.get("reason") or "").strip(),
    )


def _parse_classification_blacklists(payload: dict) -> list[tuple[str, str]]:
    raw_blacklists = payload.get("classificationBlacklists", [])
    if not isinstance(raw_blacklists, list):
        raise AcquisitionReplacementError(
            "acquisition replacement dictionary classificationBlacklists must be an array"
        )
    result: list[tuple[str, str]] = []
    for index, raw in enumerate(raw_blacklists):
        if not isinstance(raw, dict):
            raise AcquisitionReplacementError(
                f"classification blacklist #{index + 1} must be an object"
            )
        blacklist_id = _text(raw.get("id"), "id", f"blacklist-{index + 1}")
        if raw.get("status") != "accepted":
            continue
        replacement = _text(raw.get("replacement"), "replacement", blacklist_id)
        values = raw.get("values")
        if not isinstance(values, list) or not values:
            raise AcquisitionReplacementError(
                f"classification blacklist {blacklist_id} values must be a non-empty array"
            )
        for value in values:
            result.append((_text(value, "values[]", blacklist_id), replacement))
    return result


@lru_cache(maxsize=1)
def load_acquisition_replacement_dictionary() -> AcquisitionReplacementDictionary:
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcquisitionReplacementError(
            f"cannot load acquisition replacement dictionary {CONFIG_PATH}: {exc}"
        ) from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise AcquisitionReplacementError("acquisition replacement dictionary schemaVersion must be 1")
    if payload.get("reviewStatus") != "accepted":
        raise AcquisitionReplacementError("acquisition replacement dictionary is not human-accepted")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise AcquisitionReplacementError("acquisition replacement dictionary entries must be an array")
    entries = [entry for entry in (_parse_entry(raw) for raw in raw_entries) if entry is not None]
    return AcquisitionReplacementDictionary(
        entries,
        classification_blacklists=_parse_classification_blacklists(payload),
    )


def canonical_acquisition_heading(equipment_name: str, raw_text: str) -> str:
    return load_acquisition_replacement_dictionary().canonical_heading(equipment_name, raw_text)


def resolve_acquisition_context_label(raw_text: str) -> Optional[str]:
    return load_acquisition_replacement_dictionary().resolve_context_label(raw_text)


def canonical_acquisition_classification_text(raw_text: str) -> str:
    return load_acquisition_replacement_dictionary().canonical_classification_text(raw_text)


def is_acquisition_historical_marker(raw_text: str) -> bool:
    return load_acquisition_replacement_dictionary().is_historical_marker(raw_text)


def is_ignored_acquisition_text(raw_text: str) -> bool:
    return load_acquisition_replacement_dictionary().is_ignored(raw_text)
