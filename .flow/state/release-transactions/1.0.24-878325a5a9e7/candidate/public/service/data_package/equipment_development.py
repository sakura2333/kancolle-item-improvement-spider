from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from util.start2.start2_item_utils import Start2ItemUtils

SOURCE_ID = "kcwiki-equipment-development"
SCHEMA_VERSION = 1


@dataclass
class DevelopmentIssue:
    kind: str
    message: str
    equipment_id: int | None = None
    equipment_name: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source": SOURCE_ID,
            "kind": self.kind,
            "message": self.message,
        }
        if self.equipment_id is not None:
            result["equipmentId"] = self.equipment_id
        if self.equipment_name:
            result["equipmentName"] = self.equipment_name
        if self.evidence:
            result["evidence"] = self.evidence
        return result


def _normalized_name(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def parse_kcwiki_development_flags(
    equipment_catalog: Any,
    item_utils: Start2ItemUtils,
) -> tuple[list[dict[str, Any]], list[DevelopmentIssue], dict[str, Any]]:
    """Project KCWiki's ``_buildable`` flag onto canonical Start2 equipment.

    Cross-source numeric IDs are deliberately ignored.  A KCWiki entry is
    accepted only when its normalized Japanese name uniquely matches the
    canonical Start2 equipment name.
    """

    by_name: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    if isinstance(equipment_catalog, dict):
        for source_key, raw in equipment_catalog.items():
            if not isinstance(raw, dict):
                continue
            source_name = _normalized_name(raw.get("_japanese_name"))
            if source_name:
                by_name[source_name].append((str(source_key), raw))

    records: list[dict[str, Any]] = []
    issues: list[DevelopmentIssue] = []
    availability_counts: Counter[str] = Counter()
    player_items = [
        item
        for item in item_utils.items
        if int(item.get("api_id") or 0) > 0
        and int(item.get("api_sortno") or 0) > 0
    ]
    for item in player_items:
        equipment_id = int(item["api_id"])
        equipment_name = str(item.get("api_name") or "")
        normalized = _normalized_name(equipment_name)
        candidates = by_name.get(normalized, [])
        if not candidates:
            issues.append(DevelopmentIssue(
                kind="kcwiki-development-name-missing",
                message="KCWiki has no uniquely named equipment entry for this Start2 item",
                equipment_id=equipment_id,
                equipment_name=equipment_name,
                evidence={"normalizedName": normalized},
            ))
            continue
        if len(candidates) != 1:
            issues.append(DevelopmentIssue(
                kind="kcwiki-development-name-ambiguous",
                message="KCWiki has multiple entries with the same normalized Japanese name",
                equipment_id=equipment_id,
                equipment_name=equipment_name,
                evidence={
                    "normalizedName": normalized,
                    "sourceKeys": [source_key for source_key, _ in candidates],
                },
            ))
            continue

        source_key, raw = candidates[0]
        value = raw.get("_buildable")
        if not isinstance(value, bool):
            issues.append(DevelopmentIssue(
                kind="kcwiki-development-flag-invalid",
                message="KCWiki _buildable must be a non-null boolean",
                equipment_id=equipment_id,
                equipment_name=equipment_name,
                evidence={
                    "sourceKey": source_key,
                    "sourceName": raw.get("_japanese_name"),
                    "rawValue": value,
                    "rawType": type(value).__name__,
                },
            ))
            continue

        availability_counts[str(value).lower()] += 1
        records.append({
            "equipmentId": equipment_id,
            "equipmentName": equipment_name,
            "developmentAvailable": value,
            "evidence": {
                "source": "kcwiki-data",
                "matchedBy": "normalized-japanese-name-exact",
                "sourceKey": source_key,
                "sourceName": str(raw.get("_japanese_name") or ""),
                "field": "_buildable",
            },
        })

    records.sort(key=lambda record: int(record["equipmentId"]))
    metadata = {
        "source": SOURCE_ID,
        "schemaVersion": SCHEMA_VERSION,
        "playerEquipmentCount": len(player_items),
        "recordCount": len(records),
        "issueCount": len(issues),
        "developmentAvailableCount": int(availability_counts.get("true", 0)),
        "developmentUnavailableCount": int(availability_counts.get("false", 0)),
        "identityRule": "normalized-japanese-name-exact",
        "sourceIdUsedAsIdentity": False,
    }
    return records, issues, metadata
