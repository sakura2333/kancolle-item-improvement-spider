from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from service.source_validation.model import SourceResult, SourceSchedule, WEEKDAY_NAMES, normalize_week


@dataclass
class ScheduleDiff:
    candidate_source: str
    item_id: int
    item_name: str
    ship_id: Optional[int]
    ship_name: str
    capability: str
    update_target_item_id: Optional[int]
    status: str
    baseline_week: Optional[Tuple[bool, ...]]
    candidate_week: Optional[Tuple[bool, ...]]
    baseline_routes: Tuple[str, ...] = ()
    candidate_routes: Tuple[str, ...] = ()

    def to_json(self) -> dict:
        def names(week):
            if week is None:
                return None
            return [name for name, enabled in zip(WEEKDAY_NAMES, week) if enabled]

        return {
            "candidateSource": self.candidate_source,
            "itemId": self.item_id,
            "itemName": self.item_name,
            "shipId": self.ship_id,
            "shipName": self.ship_name,
            "capability": self.capability,
            "updateTargetItemId": self.update_target_item_id,
            "status": self.status,
            "baselineWeek": list(self.baseline_week) if self.baseline_week is not None else None,
            "candidateWeek": list(self.candidate_week) if self.candidate_week is not None else None,
            "baselineDays": names(self.baseline_week),
            "candidateDays": names(self.candidate_week),
            "baselineRoutes": list(self.baseline_routes),
            "candidateRoutes": list(self.candidate_routes),
        }


def _aggregate_index(schedules: Iterable[SourceSchedule]):
    result: Dict[Tuple, SourceSchedule] = {}
    routes: Dict[Tuple, List[str]] = defaultdict(list)
    for schedule in schedules:
        key = schedule.comparison_identity()
        route = schedule.route_signature or schedule.route_id
        if route and route not in routes[key]:
            routes[key].append(route)
        if key not in result:
            result[key] = copy.copy(schedule)
            continue
        current = result[key]
        current.week = normalize_week(
            left or right for left, right in zip(current.week, schedule.week)
        )
    return result, routes


def _supported_capabilities(result: SourceResult) -> set[str]:
    declared = result.metadata.get("supportedCapabilities")
    if isinstance(declared, list):
        values = {str(value).strip() for value in declared if str(value).strip()}
        if values:
            return values
    return {schedule.capability for schedule in result.schedules}


def compare_source(
    baseline: SourceResult,
    candidate: SourceResult,
) -> Tuple[List[ScheduleDiff], dict]:
    supported_capabilities = _supported_capabilities(candidate)
    comparable_baseline = [
        schedule
        for schedule in baseline.schedules
        if schedule.capability in supported_capabilities
    ]
    ignored_baseline = [
        schedule
        for schedule in baseline.schedules
        if schedule.capability not in supported_capabilities
    ]
    baseline_index, baseline_routes = _aggregate_index(comparable_baseline)
    candidate_index, candidate_routes = _aggregate_index(candidate.schedules)
    diffs: List[ScheduleDiff] = []
    counts = defaultdict(int)

    def sort_key(value):
        item_id, ship_id, capability, target_id = value
        return item_id, ship_id or 0, capability, target_id or 0

    for key in sorted(set(baseline_index) | set(candidate_index), key=sort_key):
        left = baseline_index.get(key)
        right = candidate_index.get(key)
        sample = left or right
        if left is None:
            status = "extra-in-candidate"
        elif right is None:
            status = "missing-in-candidate"
        elif left.week != right.week:
            status = "weekday-mismatch"
        else:
            status = "match"
        counts[status] += 1
        if status != "match":
            diffs.append(ScheduleDiff(
                candidate_source=candidate.source,
                item_id=sample.item_id,
                item_name=sample.item_name,
                ship_id=sample.ship_id,
                ship_name=sample.ship_name,
                capability=sample.capability,
                update_target_item_id=sample.update_target_item_id,
                status=status,
                baseline_week=left.week if left else None,
                candidate_week=right.week if right else None,
                baseline_routes=tuple(baseline_routes.get(key, ())),
                candidate_routes=tuple(candidate_routes.get(key, ())),
            ))

    comparable = counts["match"] + counts["weekday-mismatch"]
    summary = {
        "source": candidate.source,
        "status": candidate.status,
        "baselineScheduleCount": len(baseline_index),
        "candidateScheduleCount": len(candidate_index),
        "comparableScheduleCount": comparable,
        "matchCount": counts["match"],
        "weekdayMismatchCount": counts["weekday-mismatch"],
        "missingInCandidateCount": counts["missing-in-candidate"],
        "extraInCandidateCount": counts["extra-in-candidate"],
        "candidateIssueCount": len(candidate.issues),
        "supportedCapabilities": sorted(supported_capabilities),
        "ignoredUnsupportedCapabilityCount": len(ignored_baseline),
    }
    summary["agreementRate"] = (
        round(counts["match"] / comparable, 6) if comparable else None
    )
    return diffs, summary
