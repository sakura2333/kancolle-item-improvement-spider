from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from configs.path import get_data_dir
from service.source_validation.model import SourceResult, SourceSchedule, WEEKDAY_NAMES
from util.json_utils import read_json, read_json_lines, write_json, write_json_lines

HISTORY_SCHEMA_VERSION = 1


def history_root() -> Path:
    return Path(get_data_dir("sources")) / "history"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _source_name(source: str) -> str:
    return source.replace("/", "-").replace("_", "-")


def _comparison_fact_key(schedule: SourceSchedule) -> str:
    ship = "none" if schedule.ship_id is None else str(schedule.ship_id)
    target = "none" if schedule.update_target_item_id is None else str(schedule.update_target_item_id)
    return (
        f"item:{schedule.item_id}|ship:{ship}|capability:{schedule.capability}|"
        f"target:{target}"
    )


def _week_days(week: Iterable[bool]) -> List[str]:
    return [name for name, enabled in zip(WEEKDAY_NAMES, week) if enabled]


def aggregate_source_facts(result: SourceResult) -> List[dict]:
    """Collapse route-local rows into stable cross-source semantic facts.

    The observation history is intentionally broader than the route audit. It tracks
    the fact that one helper can improve one item on a set of weekdays, while retaining
    route IDs as supporting detail. This avoids noisy history when only source-local
    route labels change.
    """

    grouped: Dict[str, dict] = {}
    routes: Dict[str, set[str]] = defaultdict(set)
    parser_versions: Dict[str, set[str]] = defaultdict(set)
    source_refs: Dict[str, set[str]] = defaultdict(set)
    evidence_statuses: Dict[str, set[str]] = defaultdict(set)

    for schedule in result.schedules:
        key = _comparison_fact_key(schedule)
        if key not in grouped:
            grouped[key] = {
                "factKey": key,
                "itemId": schedule.item_id,
                "itemName": schedule.item_name,
                "shipId": schedule.ship_id,
                "shipName": schedule.ship_name,
                "capability": schedule.capability,
                "updateTargetItemId": schedule.update_target_item_id,
                "week": list(schedule.week),
            }
        else:
            grouped[key]["week"] = [
                bool(left or right)
                for left, right in zip(grouped[key]["week"], schedule.week)
            ]

        route = schedule.route_signature or schedule.route_id
        if route:
            routes[key].add(route)
        if schedule.parser_version:
            parser_versions[key].add(schedule.parser_version)
        if schedule.source_ref:
            source_refs[key].add(schedule.source_ref)
        if schedule.evidence_status:
            evidence_statuses[key].add(schedule.evidence_status)

    facts: List[dict] = []
    for key in sorted(grouped):
        fact = grouped[key]
        fact["days"] = _week_days(fact["week"])
        if routes[key]:
            fact["routes"] = sorted(routes[key])
        if parser_versions[key]:
            fact["parserVersions"] = sorted(parser_versions[key])
        if source_refs[key]:
            fact["sourceRefs"] = sorted(source_refs[key])
        if evidence_statuses[key]:
            fact["evidenceStatuses"] = sorted(evidence_statuses[key])
        if fact.get("updateTargetItemId") is None:
            fact.pop("updateTargetItemId", None)
        facts.append(fact)
    return facts


def _facts_hash(facts: Sequence[dict]) -> str:
    payload = json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_snapshot(result: SourceResult, observed_at: Optional[str] = None) -> dict:
    facts = aggregate_source_facts(result)
    return {
        "schemaVersion": HISTORY_SCHEMA_VERSION,
        "source": result.source,
        "observedAt": observed_at or _now_iso(),
        "status": result.status,
        "factCount": len(facts),
        "snapshotSha256": _facts_hash(facts),
        "facts": facts,
    }


def _index(snapshot: Optional[dict]) -> Dict[str, dict]:
    if not isinstance(snapshot, dict):
        return {}
    facts = snapshot.get("facts", [])
    if not isinstance(facts, list):
        return {}
    return {
        str(fact.get("factKey")): fact
        for fact in facts
        if isinstance(fact, dict) and fact.get("factKey")
    }


def _fact_signature(fact: Optional[dict]) -> Optional[str]:
    if fact is None:
        return None
    stable = {
        "itemId": fact.get("itemId"),
        "shipId": fact.get("shipId"),
        "capability": fact.get("capability"),
        "updateTargetItemId": fact.get("updateTargetItemId"),
        "week": fact.get("week"),
    }
    return json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _removed_keys(change_path: Path) -> set[str]:
    removed: set[str] = set()
    for event in read_json_lines(change_path):
        if not isinstance(event, dict):
            continue
        key = str(event.get("factKey", ""))
        if not key:
            continue
        change_type = event.get("changeType")
        if change_type == "removed":
            removed.add(key)
        elif change_type in {"added", "reappeared"}:
            removed.discard(key)
    return removed


def _diff_snapshots(previous: Optional[dict], current: dict, removed_before: set[str]) -> List[dict]:
    previous_index = _index(previous)
    current_index = _index(current)
    events: List[dict] = []

    for key in sorted(set(previous_index) | set(current_index)):
        before = previous_index.get(key)
        after = current_index.get(key)
        if before is None:
            change_type = "reappeared" if key in removed_before else "added"
        elif after is None:
            change_type = "removed"
        elif _fact_signature(before) != _fact_signature(after):
            change_type = "modified"
        else:
            continue

        before_versions = sorted(before.get("parserVersions", [])) if before else []
        after_versions = sorted(after.get("parserVersions", [])) if after else []
        origin = (
            "parser-version-changed"
            if before is not None and after is not None and before_versions != after_versions
            else "source-observed"
        )
        events.append({
            "schemaVersion": HISTORY_SCHEMA_VERSION,
            "source": current["source"],
            "factKey": key,
            "changeType": change_type,
            "changeOrigin": origin,
            "before": before,
            "after": after,
        })
    return events


def _peer_assessment(event: dict, source: str, snapshots: Mapping[str, dict]) -> dict:
    key = event["factKey"]
    change_type = event["changeType"]
    peers = {
        peer_source: _index(snapshot).get(key)
        for peer_source, snapshot in snapshots.items()
        if peer_source != source
    }
    present = {name: fact for name, fact in peers.items() if fact is not None}
    signatures = Counter(_fact_signature(fact) for fact in present.values())

    if change_type == "removed":
        if not present:
            return {"peerAssessment": "unconfirmed", "peerEvidenceCount": 0}
        most_common = signatures.most_common(1)[0][1]
        assessment = "outlier" if most_common >= 2 else "unconfirmed"
        return {
            "peerAssessment": assessment,
            "peerEvidenceCount": len(present),
            "peerSources": sorted(present),
        }

    after_signature = _fact_signature(event.get("after"))
    agreeing = sorted(
        name for name, fact in present.items()
        if _fact_signature(fact) == after_signature
    )
    if agreeing:
        return {
            "peerAssessment": "corroborated",
            "peerEvidenceCount": len(agreeing),
            "peerSources": agreeing,
        }

    if signatures and signatures.most_common(1)[0][1] >= 2:
        return {
            "peerAssessment": "outlier",
            "peerEvidenceCount": len(present),
            "peerSources": sorted(present),
        }
    return {
        "peerAssessment": "unconfirmed",
        "peerEvidenceCount": len(present),
        "peerSources": sorted(present),
    }


def observe_source_history(
    results: Sequence[SourceResult],
    *,
    root: Optional[Path] = None,
    observed_at: Optional[str] = None,
) -> dict:
    """Create the one-time baseline, then append only semantic change events.

    Results that are not ``ok`` are deliberately skipped. A parser failure must not be
    recorded as a mass deletion from the website.
    """

    root = Path(root) if root is not None else history_root()
    observed_at = observed_at or _now_iso()
    root.mkdir(parents=True, exist_ok=True)
    (root / "baseline").mkdir(parents=True, exist_ok=True)
    (root / "current").mkdir(parents=True, exist_ok=True)
    (root / "changes").mkdir(parents=True, exist_ok=True)

    eligible = [result for result in results if result.status == "ok"]
    skipped = [result.source for result in results if result.status != "ok"]
    snapshots = {
        result.source: build_snapshot(result, observed_at)
        for result in eligible
    }

    source_summaries: List[dict] = []
    all_events: Dict[str, List[dict]] = {}
    previous_snapshots: Dict[str, Optional[dict]] = {}

    for source, snapshot in snapshots.items():
        safe = _source_name(source)
        current_path = root / "current" / f"{safe}.json"
        baseline_path = root / "baseline" / f"{safe}.json"
        previous = read_json(current_path)
        if not isinstance(previous, dict) and baseline_path.exists():
            previous = read_json(baseline_path)
        previous_snapshots[source] = previous if isinstance(previous, dict) else None
        change_path = root / "changes" / f"{safe}.nedb"
        events = _diff_snapshots(previous_snapshots[source], snapshot, _removed_keys(change_path))
        all_events[source] = events

    for source, events in all_events.items():
        for event in events:
            event["observedAt"] = observed_at
            event.update(_peer_assessment(event, source, snapshots))

    existing_manifest = read_json(root / "manifest.json")
    manifest = existing_manifest if isinstance(existing_manifest, dict) else {}
    source_manifest = manifest.get("sources", {}) if isinstance(manifest.get("sources"), dict) else {}

    for source, snapshot in snapshots.items():
        safe = _source_name(source)
        baseline_path = root / "baseline" / f"{safe}.json"
        current_path = root / "current" / f"{safe}.json"
        change_path = root / "changes" / f"{safe}.nedb"
        initialized = not baseline_path.exists()
        current_missing = not current_path.exists()
        if initialized:
            write_json(baseline_path, snapshot, mode="w", log=False)
            write_json(current_path, snapshot, mode="w", log=False)
            events: List[dict] = []
        else:
            baseline = read_json(baseline_path)
            if not isinstance(baseline, dict) or not isinstance(baseline.get("facts"), list):
                raise ValueError(f"invalid source history baseline: {baseline_path}")
            events = all_events[source]
            if events:
                write_json_lines(change_path, events, mode="a", log=False)
            if events or current_missing:
                write_json(current_path, snapshot, mode="w", log=False)

        previous_entry = source_manifest.get(source, {}) if isinstance(source_manifest.get(source), dict) else {}
        previous_event_count = int(previous_entry.get("eventCount", 0) or 0)
        entry = {
            "baselineSnapshotSha256": read_json(baseline_path).get("snapshotSha256"),
            "currentSnapshotSha256": snapshot["snapshotSha256"],
            "currentFactCount": snapshot["factCount"],
            "eventCount": previous_event_count + len(events),
            "lastObservedAt": observed_at,
        }
        if initialized:
            entry["baselineCreatedAt"] = observed_at
        elif previous_entry.get("baselineCreatedAt"):
            entry["baselineCreatedAt"] = previous_entry["baselineCreatedAt"]
        if events:
            entry["lastChangeAt"] = observed_at
        elif previous_entry.get("lastChangeAt"):
            entry["lastChangeAt"] = previous_entry["lastChangeAt"]
        source_manifest[source] = entry

        counts = Counter(event["changeType"] for event in events)
        assessments = Counter(event.get("peerAssessment", "unconfirmed") for event in events)
        source_summaries.append({
            "source": source,
            "initializedBaseline": initialized,
            "factCount": snapshot["factCount"],
            "snapshotChanged": bool(events),
            "changeCount": len(events),
            "addedCount": counts["added"],
            "removedCount": counts["removed"],
            "modifiedCount": counts["modified"],
            "reappearedCount": counts["reappeared"],
            "corroboratedCount": assessments["corroborated"],
            "outlierCount": assessments["outlier"],
            "unconfirmedCount": assessments["unconfirmed"],
        })

    run_count = int(manifest.get("runCount", 0) or 0) + 1
    run = {
        "schemaVersion": HISTORY_SCHEMA_VERSION,
        "observedAt": observed_at,
        "runNumber": run_count,
        "sources": source_summaries,
        "skippedSources": sorted(skipped),
    }
    write_json_lines(root / "runs.nedb", [run], mode="a", log=False)

    manifest = {
        "schemaVersion": HISTORY_SCHEMA_VERSION,
        "mode": "one-time-baseline-then-incremental-events",
        "baselineCreatedAt": manifest.get("baselineCreatedAt", observed_at),
        "lastObservedAt": observed_at,
        "runCount": run_count,
        "sources": source_manifest,
    }
    write_json(root / "manifest.json", manifest, mode="w", log=False)
    return run
