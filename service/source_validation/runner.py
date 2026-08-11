from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Callable, Dict, List, Sequence

from service.data_package.improvement_record import WeaponItemVO
from service.source_validation.ai_review import export_ai_review_input
from service.source_validation.common import schedules_from_primary
from service.source_validation.compare import compare_source
from service.source_validation.export import export_comparison, export_source
from service.source_validation.history import observe_source_history
from service.source_validation.kcwiki_data import (
    EQUIPMENT_URL as KCWIKI_DATA_URL,
    collect as collect_kcwiki_data,
)
from service.source_validation.model import SourceResult
from service.source_validation.reliability import export_source_reliability
from service.source_validation.semantic_aliases import validate_semantic_alias_dictionary
from service.source_validation.wikiwiki_jp import (
    SOURCE_URL as WIKIWIKI_JP_URL,
    collect as collect_wikiwiki_jp,
)
from util.logger import simple_logger
from util.site_workers import SiteTask, run_site_tasks
from util.start2.start2_item_utils import start2ItemUtils
from util.start2.start2_ship_utils import ship_utils

COLLECTORS: Dict[str, Callable] = {
    "wikiwiki-jp": collect_wikiwiki_jp,
    "kcwiki-data": collect_kcwiki_data,
}
DEFAULT_SOURCES = tuple(COLLECTORS)
SOURCE_URLS = {
    "wikiwiki-jp": WIKIWIKI_JP_URL,
    "kcwiki-data": KCWIKI_DATA_URL,
}


def _enabled_sources() -> List[str]:
    raw = os.getenv("VALIDATION_SOURCES", ",".join(DEFAULT_SOURCES)).strip()
    if not raw:
        return []
    return [value.strip() for value in raw.split(",") if value.strip()]


def _strict() -> bool:
    for name in ("VALIDATION_STRICT", "DATA_PACKAGE_STRICT"):
        if os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _collect_one(source: str, loaded_items, loaded_ships) -> SourceResult:
    collector = COLLECTORS.get(source)
    if collector is None:
        raise ValueError(f"unknown source adapter: {source}")
    return collector(loaded_items, loaded_ships)


def _collect_by_site(sources: List[str], loaded_items, loaded_ships) -> Dict[str, SourceResult | Exception]:
    tasks = [
        SiteTask(
            key=source,
            url=SOURCE_URLS.get(source, f"adapter://{source}"),
            callback=lambda current=source: _collect_one(current, loaded_items, loaded_ships),
        )
        for source in sources
    ]
    return run_site_tasks(tasks)


def run_source_validation(items: Sequence[WeaponItemVO], *, record_history: bool = True):
    loaded_items = start2ItemUtils.load()
    loaded_ships = ship_utils.load()
    alias_validation = validate_semantic_alias_dictionary(loaded_items, loaded_ships)
    simple_logger.info(
        "[semantic aliases] "
        f"validated={alias_validation['validatedTargetCount']}/"
        f"{alias_validation['entryCount']} against Start2"
    )
    baseline = SourceResult(
        source="akashi-list",
        url="https://akashi-list.me/",
        schedules=schedules_from_primary(items, loaded_ships),
        metadata={
            "role": "canonical-output-source",
            "supportedCapabilities": ["improve", "upgrade"],
            "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        },
    )
    export_source(baseline)

    enabled_sources = _enabled_sources()
    collected = _collect_by_site(enabled_sources, loaded_items, loaded_ships)
    candidates: List[SourceResult] = []
    failures: List[Exception] = []
    strict = _strict()

    for source in enabled_sources:
        value = collected.get(source)
        if isinstance(value, Exception) or value is None:
            exc = value if isinstance(value, Exception) else RuntimeError("collector returned no result")
            if source == "kcwiki-data":
                simple_logger.error(
                    "[KCWIKI RAW UNAVAILABLE][NON-BLOCKING] "
                    f"source validation skipped: {type(exc).__name__}: {exc}"
                )
            else:
                simple_logger.error(f"[source validation] {source} failed: {exc}")
            result = SourceResult(
                source=source,
                url=SOURCE_URLS.get(source, ""),
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            if source != "kcwiki-data":
                failures.append(exc)
        else:
            result = value
            if strict and result.status != "ok":
                failures.append(RuntimeError(
                    f"validation source {source} is {result.status}: "
                    f"issues={len(result.issues)}, "
                    f"unresolvedShips={result.metadata.get('unresolvedShipCount', 0)}, "
                    f"unresolvedItems={result.metadata.get('unresolvedItemCount', 0)}"
                ))
        candidates.append(result)
        export_source(result)

    all_diffs = []
    summaries = []
    for candidate in candidates:
        if candidate.status == "failed":
            summaries.append({
                "source": candidate.source,
                "status": candidate.status,
                "baselineScheduleCount": len(baseline.schedules),
                "candidateScheduleCount": 0,
                "comparableScheduleCount": 0,
                "matchCount": 0,
                "weekdayMismatchCount": 0,
                "missingInCandidateCount": 0,
                "extraInCandidateCount": 0,
                "candidateIssueCount": len(candidate.issues),
                "supportedCapabilities": list(candidate.metadata.get("supportedCapabilities", [])),
                "ignoredUnsupportedCapabilityCount": 0,
                "agreementRate": None,
            })
            continue
        diffs, summary = compare_source(baseline, candidate)
        summary["status"] = candidate.status
        all_diffs.extend(diffs)
        summaries.append(summary)
        simple_logger.info(
            "[source validation] "
            f"{candidate.source}: status={candidate.status}, match={summary['matchCount']}, "
            f"weekdayMismatch={summary['weekdayMismatchCount']}, "
            f"missing={summary['missingInCandidateCount']}, "
            f"extra={summary['extraInCandidateCount']}, "
            f"issues={summary['candidateIssueCount']}, "
            f"unresolvedShips={candidate.metadata.get('unresolvedShipCount', 0)}, "
            f"unresolvedItems={candidate.metadata.get('unresolvedItemCount', 0)}, "
            f"semanticAliases={candidate.metadata.get('semanticAliasMatchCount', 0)}"
        )

    export_comparison(baseline, candidates, all_diffs, summaries)
    export_ai_review_input(baseline, candidates, all_diffs, summaries)

    observed_results = [baseline, *[candidate for candidate in candidates if candidate.status == "ok"]]
    if record_history:
        history_run = observe_source_history(observed_results)
        simple_logger.info(
            "[source history] "
            f"run={history_run['runNumber']}, "
            f"changes={sum(row['changeCount'] for row in history_run['sources'])}, "
            f"baselines={sum(1 for row in history_run['sources'] if row['initializedBaseline'])}"
        )
    else:
        simple_logger.info("[source history] skipped for diagnostic-only comparison")
    reliability = export_source_reliability(observed_results)
    simple_logger.info(
        "[source reliability] "
        + ", ".join(
            f"{row['source']}={row['relativeWeight']:.4f}/{row['confidence']}"
            for row in reliability['sources']
        )
    )
    if failures and strict:
        raise RuntimeError(f"{len(failures)} validation source(s) failed quality requirements") from failures[0]
    return baseline, candidates, all_diffs, summaries
