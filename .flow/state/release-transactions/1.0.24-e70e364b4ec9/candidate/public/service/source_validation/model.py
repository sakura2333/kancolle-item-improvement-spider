from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

WEEKDAY_NAMES = [
    "sunday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
]


def normalize_week(values: Iterable[bool]) -> Tuple[bool, ...]:
    week = tuple(bool(value) for value in values)
    if len(week) != 7:
        raise ValueError(f"week must contain seven values, got {len(week)}")
    return week


@dataclass
class SourceSchedule:
    """Normalized equipment/helper fact from one source.

    The full identity preserves route and update-target differences for audit.
    Cross-source availability comparison can use :meth:`comparison_identity`,
    which intentionally ignores source-local route labels.
    """

    source: str
    item_id: int
    item_name: str
    ship_id: Optional[int]
    ship_name: str
    week: Tuple[bool, ...]
    capability: str = "improve"
    update_target_item_id: Optional[int] = None
    route_id: str = ""
    route_signature: str = ""
    evidence_status: str = "explicit-yes"
    parser_version: str = ""
    source_ref: str = ""
    raw_text: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)

    def identity(self) -> Tuple[int, Optional[int], str, Optional[int], str]:
        return (
            self.item_id,
            self.ship_id,
            self.capability,
            self.update_target_item_id,
            self.route_signature or self.route_id,
        )

    def comparison_identity(self) -> Tuple[int, Optional[int], str, Optional[int]]:
        return (
            self.item_id,
            self.ship_id,
            self.capability,
            self.update_target_item_id,
        )

    def fact_key(self) -> str:
        ship = "none" if self.ship_id is None else str(self.ship_id)
        target = "none" if self.update_target_item_id is None else str(self.update_target_item_id)
        route = self.route_signature or self.route_id or "unspecified"
        return (
            f"item:{self.item_id}|ship:{ship}|capability:{self.capability}|"
            f"target:{target}|route:{route}"
        )

    def to_json(self) -> dict:
        result = {
            "factKey": self.fact_key(),
            "source": self.source,
            "itemId": self.item_id,
            "itemName": self.item_name,
            "shipId": self.ship_id,
            "shipName": self.ship_name,
            "week": list(self.week),
            "capability": self.capability,
            "evidenceStatus": self.evidence_status,
        }
        for key, value in (
            ("updateTargetItemId", self.update_target_item_id),
            ("routeId", self.route_id),
            ("routeSignature", self.route_signature),
            ("parserVersion", self.parser_version),
            ("sourceRef", self.source_ref),
            ("rawText", self.raw_text),
        ):
            if value is not None and value != "":
                result[key] = value
        if self.evidence:
            result["evidence"] = self.evidence
        return result


@dataclass
class SourceIssue:
    source: str
    kind: str
    message: str
    source_ref: str = ""
    item_name: str = ""
    ship_name: str = ""
    raw_text: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict:
        result = {
            "source": self.source,
            "kind": self.kind,
            "message": self.message,
        }
        for key, value in (
            ("sourceRef", self.source_ref),
            ("itemName", self.item_name),
            ("shipName", self.ship_name),
            ("rawText", self.raw_text),
        ):
            if value:
                result[key] = value
        if self.evidence:
            result["evidence"] = self.evidence
        return result


@dataclass
class SourceResult:
    source: str
    url: str
    schedules: List[SourceSchedule] = field(default_factory=list)
    issues: List[SourceIssue] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: str = ""

    def to_metadata_json(self) -> dict:
        result = {
            "source": self.source,
            "url": self.url,
            "status": self.status,
            "scheduleCount": len(self.schedules),
            "issueCount": len(self.issues),
            **self.metadata,
        }
        if self.error:
            result["error"] = self.error
        return result
