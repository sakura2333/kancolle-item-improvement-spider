from __future__ import annotations

import json
import os
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

from service.source_validation.compare import ScheduleDiff
from service.source_validation.export import source_root
from service.source_validation.model import SourceResult, SourceSchedule
from util.json_utils import write_json, write_json_lines

SCHEMA_VERSION = 1


def _prompt_source_path() -> Path:
    return Path(__file__).resolve().parent / "prompts" / "ai_review.md"


def _route_variants(schedules: Iterable[SourceSchedule]):
    """Return item-level recipe variants, including disjoint assistant routes."""
    by_item = defaultdict(dict)
    for schedule in schedules:
        route = schedule.route_signature or schedule.route_id or "unspecified"
        route_entry = by_item[schedule.item_id].setdefault(route, {
            "itemId": schedule.item_id,
            "itemName": schedule.item_name,
            "routeId": schedule.route_id,
            "routeSignature": schedule.route_signature,
            "shipIds": [],
            "capabilities": [],
            "updateTargetItemIds": [],
            "evidence": schedule.evidence,
        })
        if schedule.ship_id is not None and schedule.ship_id not in route_entry["shipIds"]:
            route_entry["shipIds"].append(schedule.ship_id)
        if schedule.capability not in route_entry["capabilities"]:
            route_entry["capabilities"].append(schedule.capability)
        target = schedule.update_target_item_id
        if target is not None and target not in route_entry["updateTargetItemIds"]:
            route_entry["updateTargetItemIds"].append(target)

    result = []
    for item_id, route_map in by_item.items():
        if len(route_map) <= 1:
            continue
        routes = list(route_map.values())
        result.append({
            "itemId": item_id,
            "itemName": routes[0]["itemName"],
            "routes": routes,
        })
    return result


def _preliminary_decisions(results: List[SourceResult]):
    grouped = defaultdict(list)
    for result in results:
        for schedule in result.schedules:
            grouped[schedule.comparison_identity()].append(schedule)

    decisions = []
    for key, evidence in grouped.items():
        explicit = [e for e in evidence if e.evidence_status == "explicit-yes"]
        inferred = [e for e in evidence if e.evidence_status == "inferred-yes"]
        sample = evidence[0]
        if len({e.source for e in explicit}) >= 2:
            decision = "accept"
            confidence = "high"
        elif explicit:
            decision = "accept"
            confidence = "medium"
        elif inferred:
            decision = "accept-inferred"
            confidence = "low"
        else:
            decision = "insufficient"
            confidence = "low"
        decisions.append({
            "factKey": sample.fact_key(),
            "comparisonKey": list(key),
            "decision": decision,
            "confidence": confidence,
            "evidenceSources": list(dict.fromkeys(e.source for e in evidence)),
            "note": "Preliminary deterministic classification; AI and human review must not treat it as an automatic correction.",
        })
    return decisions


def export_ai_review_input(
    baseline: SourceResult,
    candidates: List[SourceResult],
    diffs: List[ScheduleDiff],
    summaries: List[dict],
):
    directory = os.path.join(source_root(), "ai-review")
    os.makedirs(directory, exist_ok=True)
    prompt_target = os.path.join(directory, "review-prompt.md")
    shutil.copyfile(_prompt_source_path(), prompt_target)

    results = [baseline] + candidates
    previous_review_path = os.path.join(directory, "report.json")
    previous_review = None
    if os.path.exists(previous_review_path):
        try:
            with open(previous_review_path, "r", encoding="utf-8") as file:
                previous_review = json.load(file)
        except Exception:
            previous_review = {"status": "unreadable"}

    payload = {
        "metadata": {
            "schemaVersion": SCHEMA_VERSION,
            "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "reviewMode": "full",
            "minimumFactUnit": [
                "itemId",
                "shipId",
                "day",
                "capability",
                "updateTargetItemId",
                "routeSignature",
            ],
            "promptFile": "review-prompt.md",
        },
        "sourceHealth": [result.to_metadata_json() for result in results],
        "sourceSummaries": summaries,
        "sourceEvidence": {
            result.source: [schedule.to_json() for schedule in result.schedules]
            for result in results
        },
        "conflicts": [diff.to_json() for diff in diffs],
        "unresolved": [
            issue.to_json()
            for result in results
            for issue in result.issues
        ],
        "routeVariants": _route_variants(baseline.schedules),
        "consensusDecisions": _preliminary_decisions(results),
        "previousReview": previous_review,
    }
    write_json(os.path.join(directory, "input.json"), payload, mode="w", log=True)
    write_json_lines(
        os.path.join(directory, "route-variants.nedb"),
        payload["routeVariants"],
        mode="w",
        log=True,
    )
    write_json_lines(
        os.path.join(directory, "conflicts.nedb"),
        payload["conflicts"],
        mode="w",
        log=True,
    )
    with open(os.path.join(directory, "README.md"), "w", encoding="utf-8") as file:
        file.write(
            "# AI review bundle\n\n"
            "Send `review-prompt.md` together with `input.json` to the review model.\n"
            "Write the model's JSON output to `report.json`. The report is advisory and never changes public data automatically.\n"
            "For routine runs, filter `input.json` to new conflicts, unresolved items and changed route variants.\n"
        )
