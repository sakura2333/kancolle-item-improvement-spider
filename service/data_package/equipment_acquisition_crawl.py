from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from service.data_package.acquisition_references import (
    QUEST_DATA_URL,
    QuestReferenceCatalog,
    ShipReferenceCatalog,
    resolve_record_references,
)
from service.data_package.equipment_acquisition import (
    CATALOG_URL,
    SOURCE_ID,
    build_page_name_candidates,
    build_page_url,
    parse_equipment_acquisition_page,
    parse_equipment_catalog_page,
)
from service.data_package.package_paths import SOURCE_ROOT
from util.cache import fetch, get_fetch_meta
from util.json_utils import write_json, write_json_lines
from util.logger import simple_logger
from util.start2.start2_item_utils import start2ItemUtils

DEFAULT_OUTPUT_DIR = SOURCE_ROOT / SOURCE_ID


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _fetch_summary(url: str) -> dict:
    meta = get_fetch_meta(url)
    return {
        "url": url,
        "fetchStatus": meta.get("fetch_status"),
        "statusCode": meta.get("status_code"),
        "validatedAt": meta.get("validated_at"),
        "validatedInRun": bool(meta.get("validated_in_run")),
        "usedCacheFallback": bool(meta.get("used_cache_fallback")),
        "contentSha256": meta.get("content_sha256"),
        "cachePath": meta.get("cache_path"),
    }


def player_equipment_items() -> list[dict]:
    items = start2ItemUtils.load().items
    return sorted(
        (
            item for item in items
            if int(item.get("api_id", 0)) > 0
            and int(item.get("api_id", 0)) < 1000
            and int(item.get("api_sortno", 0)) > 0
        ),
        key=lambda item: int(item["api_id"]),
    )


def _candidate_urls(item: dict, catalog_by_id: dict[int, dict]) -> list[tuple[str, str]]:
    equipment_id = int(item["api_id"])
    result: list[tuple[str, str]] = []
    catalog_entry = catalog_by_id.get(equipment_id)
    if catalog_entry:
        result.append(("catalog", str(catalog_entry["sourceUrl"])))
    for page_name in build_page_name_candidates(str(item.get("api_name") or "")):
        url = build_page_url(page_name)
        if all(existing_url != url for _, existing_url in result):
            result.append(("start2-name", url))
    return result


def _fetch_equipment_page(
    item: dict,
    catalog_by_id: dict[int, dict],
    *,
    fetch_text: Callable[[str], str],
) -> tuple[str, str, list[dict]]:
    attempts: list[dict] = []
    last_error: Exception | None = None
    for candidate_source, url in _candidate_urls(item, catalog_by_id):
        try:
            html = fetch_text(url)
            attempts.append({
                "candidateSource": candidate_source,
                "status": "ok",
                **_fetch_summary(url),
            })
            return html, url, attempts
        except Exception as exc:
            last_error = exc
            attempts.append({
                "candidateSource": candidate_source,
                "url": url,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            })
    raise RuntimeError(
        f"all WikiWiki page candidates failed for equipment "
        f"{item['api_id']} {item.get('api_name')}: {last_error}"
    )


def _ship_ref_summary(ref: dict | None) -> dict | None:
    if not isinstance(ref, dict):
        return None
    ship_id = ref.get("canonicalShipId") or ref.get("shipId")
    ship_name = ref.get("canonicalShipName") or ref.get("shipName")
    if isinstance(ref.get("start2Ship"), dict):
        ship_id = ref["start2Ship"].get("shipId", ship_id)
        ship_name = ref["start2Ship"].get("shipName", ship_name)
    if ship_id is None and ship_name is None:
        return None
    result = {"shipId": ship_id, "shipName": ship_name}
    return {key: value for key, value in result.items() if value is not None}


def _diagnostic_candidate_ships(ref: dict | None) -> list[dict]:
    if not isinstance(ref, dict):
        return []
    candidates = ref.get("candidateShips")
    if isinstance(candidates, list):
        result = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            ship_id = candidate.get("shipId") or candidate.get("id")
            ship_name = candidate.get("shipName") or candidate.get("name")
            if ship_id is None and ship_name is None:
                continue
            result.append({"shipId": ship_id, "shipName": ship_name})
        if result:
            return result
    ids = ref.get("candidateShipIds") if isinstance(ref.get("candidateShipIds"), list) else []
    names = ref.get("candidateShipNames") if isinstance(ref.get("candidateShipNames"), list) else []
    return [
        {"shipId": ship_id, "shipName": names[index] if index < len(names) else None}
        for index, ship_id in enumerate(ids)
    ]


def _reference_diagnostic_rows(
    *,
    records: list[dict],
    reference_issues: list[dict],
) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()

    def append(row: dict) -> None:
        key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if key in seen:
            return
        seen.add(key)
        rows.append(row)

    for record in records:
        for method_index, method in enumerate(record.get("methods", [])):
            for ref in method.get("shipReferences", []):
                if not isinstance(ref, dict):
                    continue
                cross = ref.get("shipPageCrossValidation")
                if not isinstance(cross, dict) or cross.get("status") != "accepted":
                    continue
                append({
                    "category": "resolved-link-target-conflict",
                    "status": "resolved",
                    "equipmentId": record.get("equipmentId"),
                    "equipmentName": record.get("equipmentName"),
                    "methodIndex": method_index,
                    "rawName": ref.get("rawName") or ref.get("linkText"),
                    "linkTarget": ref.get("linkTarget"),
                    "linkHref": ref.get("linkHref"),
                    "resolution": ref.get("resolution"),
                    "reason": cross.get("reason"),
                    "acceptedShip": _ship_ref_summary(ref),
                    "linkTextShip": _ship_ref_summary(cross.get("linkTextReference")),
                    "linkPageShip": _ship_ref_summary(cross.get("linkPageReference")),
                    "candidateShips": _diagnostic_candidate_ships(cross),
                    "sourceUrl": record.get("sourceUrl"),
                })

    for issue in reference_issues:
        if not isinstance(issue, dict):
            continue
        ref = issue.get("reference") if isinstance(issue.get("reference"), dict) else {}
        cross = ref.get("shipPageCrossValidation") if isinstance(ref, dict) else None
        append({
            "category": "operator-stop-reference",
            "status": "unresolved",
            "kind": issue.get("kind"),
            "message": issue.get("message"),
            "equipmentId": issue.get("equipmentId"),
            "equipmentName": issue.get("equipmentName"),
            "methodIndex": issue.get("methodIndex"),
            "rawName": ref.get("rawName"),
            "linkTarget": ref.get("linkTarget"),
            "linkHref": ref.get("linkHref"),
            "candidateShipIds": ref.get("candidateShipIds"),
            "candidateShipNames": ref.get("candidateShipNames"),
            "candidateShips": _diagnostic_candidate_ships(ref),
            "crossValidation": cross,
            "sourceUrl": issue.get("sourceUrl"),
        })
    return rows


def reference_diagnostic_summary(
    *,
    records: list[dict],
    reference_issues: list[dict],
) -> dict:
    rows = _reference_diagnostic_rows(records=records, reference_issues=reference_issues)
    counts = Counter(row.get("category", "unknown") for row in rows)
    return {
        "schemaVersion": 1,
        "source": SOURCE_ID,
        "status": "passed" if not reference_issues else "operator-stop",
        "resolvedLinkTargetConflictCount": int(counts.get("resolved-link-target-conflict", 0)),
        "operatorStopReferenceCount": int(counts.get("operator-stop-reference", 0)),
        "rows": rows,
    }


def _format_ship(value: dict | None) -> str:
    if not isinstance(value, dict):
        return ""
    ship_id = value.get("shipId")
    ship_name = value.get("shipName")
    if ship_id is None and ship_name is None:
        return ""
    return f"{ship_id}:{ship_name}" if ship_id is not None else str(ship_name)


def _write_reference_diagnostics(
    output_dir: Path,
    *,
    records: list[dict],
    reference_issues: list[dict],
) -> dict:
    summary = reference_diagnostic_summary(records=records, reference_issues=reference_issues)
    write_json(output_dir / "reference-diagnostics.json", summary, log=False)
    lines = [
        "# WikiWiki reference diagnostics",
        "",
        f"- status: {summary['status']}",
        f"- resolvedLinkTargetConflictCount: {summary['resolvedLinkTargetConflictCount']}",
        f"- operatorStopReferenceCount: {summary['operatorStopReferenceCount']}",
        "",
    ]
    for row in summary["rows"]:
        accepted = _format_ship(row.get("acceptedShip"))
        candidates = ", ".join(
            _format_ship(candidate)
            for candidate in row.get("candidateShips", [])
            if _format_ship(candidate)
        )
        lines.extend([
            f"## {row.get('category')} {row.get('equipmentId')}:{row.get('equipmentName')}",
            "",
            f"- rawName: {row.get('rawName')}",
            f"- linkTarget: {row.get('linkTarget')}",
            f"- acceptedShip: {accepted}",
            f"- candidates: {candidates}",
            f"- reason: {row.get('reason') or row.get('kind') or row.get('message')}",
            f"- sourceUrl: {row.get('sourceUrl')}",
            "",
        ])
    (output_dir / "reference-diagnostics.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return summary


def write_acquisition_outputs(
    output_dir: Path,
    *,
    catalog: list[dict],
    records: list[dict],
    issues: list[dict],
    metadata: dict,
    reference_issues: list[dict] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    reference_issues = reference_issues or []
    diagnostic_summary = _write_reference_diagnostics(
        output_dir,
        records=records,
        reference_issues=reference_issues,
    )
    metadata.update({
        "referenceDiagnosticCounts": {
            "resolvedLinkTargetConflict": diagnostic_summary["resolvedLinkTargetConflictCount"],
            "operatorStopReference": diagnostic_summary["operatorStopReferenceCount"],
        },
        "referenceDiagnosticsJson": "reference-diagnostics.json",
        "referenceDiagnosticsMarkdown": "reference-diagnostics.md",
    })
    write_json(output_dir / "catalog.json", catalog, log=False)
    write_json_lines(output_dir / "acquisition-records.nedb", records, log=False)
    write_json_lines(output_dir / "dataset-issues.nedb", issues, log=False)
    write_json_lines(
        output_dir / "reference-issues.nedb",
        reference_issues,
        log=False,
    )
    unclassified = []
    for record in records:
        for method in record.get("methods", []):
            if method.get("types") == ["other"]:
                unclassified.append({
                    "equipmentId": record["equipmentId"],
                    "equipmentName": record["equipmentName"],
                    "sourceUrl": record["sourceUrl"],
                    **method,
                })
    write_json_lines(output_dir / "unclassified-evidence.nedb", unclassified, log=False)
    write_json(output_dir / "dataset-metadata.json", metadata, log=False)


def build_acquisition_metadata(
    *,
    mode: str,
    started_at: str,
    catalog_fetch: dict | None,
    catalog: list[dict],
    catalog_issues: list[dict],
    selected_items: list[dict],
    records: list[dict],
    issues: list[dict],
    reference_issues: list[dict],
    quest_catalog_available: bool,
    quest_catalog_count: int,
    quest_catalog_fetch: dict | None,
) -> dict:
    coverage = Counter(record.get("coverageStatus", "unknown") for record in records)
    current_types = Counter()
    historical_types = Counter()
    availability = Counter()
    for record in records:
        current_types.update(record.get("currentMethodTypes", []))
        historical_types.update(record.get("historicalMethodTypes", []))
        availability.update(
            method.get("availability", "unknown")
            for method in record.get("methods", [])
        )
    issue_kinds = Counter(issue.get("kind", "unknown") for issue in issues)
    reference_issue_kinds = Counter(
        issue.get("kind", "unknown") for issue in reference_issues
    )
    ship_reference_status = Counter()
    quest_reference_status = Counter()
    ship_reference_count = 0
    quest_reference_count = 0
    for record in records:
        for method in record.get("methods", []):
            for ref in method.get("shipReferences", []):
                ship_reference_count += 1
                ship_reference_status.update([ref.get("status", "unknown")])
            for ref in method.get("questReferences", []):
                quest_reference_count += 1
                quest_reference_status.update([ref.get("status", "unknown")])
    record_ids = {int(record["equipmentId"]) for record in records}
    selected_ids = {int(item["api_id"]) for item in selected_items}
    catalog_ids = {int(entry["equipmentId"]) for entry in catalog}
    return {
        "schemaVersion": 1,
        "source": SOURCE_ID,
        "mode": mode,
        "startedAt": started_at,
        "generatedAt": _utc_now(),
        "catalogUrl": CATALOG_URL,
        "catalogFetch": catalog_fetch,
        "catalogEntryCount": len(catalog),
        "catalogIssueCount": len(catalog_issues),
        "start2PlayerEquipmentCount": len(player_equipment_items()),
        "selectedEquipmentCount": len(selected_items),
        "recordCount": len(records),
        "acceptedRecordCount": sum(bool(record.get("accepted")) for record in records),
        "issueCount": len(issues),
        "missingRecordCount": len(selected_ids - record_ids),
        "missingFromCatalogCount": len(selected_ids - catalog_ids),
        "coverageStatusCounts": dict(sorted(coverage.items())),
        "issueKindCounts": dict(sorted(issue_kinds.items())),
        "referenceIssueCount": len(reference_issues),
        "referenceIssueKindCounts": dict(sorted(reference_issue_kinds.items())),
        "shipReferenceCount": ship_reference_count,
        "shipReferenceStatusCounts": dict(sorted(ship_reference_status.items())),
        "questReferenceCount": quest_reference_count,
        "questReferenceStatusCounts": dict(sorted(quest_reference_status.items())),
        "questCatalogAvailable": quest_catalog_available,
        "questCatalogRecordCount": quest_catalog_count,
        "questCatalogUrl": QUEST_DATA_URL,
        "questCatalogFetch": quest_catalog_fetch,
        "currentMethodTypeCounts": dict(sorted(current_types.items())),
        "historicalMethodTypeCounts": dict(sorted(historical_types.items())),
        "availabilityCounts": dict(sorted(availability.items())),
        "unclassifiedEvidenceCount": sum(
            int(record.get("unclassifiedEvidenceCount", 0)) for record in records
        ),
        "canonicalDataChanged": False,
        "canonicalDataset": "equipment/drop-from.nedb remains unchanged",
    }


def run_full_crawl(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    equipment_ids: Iterable[int] | None = None,
    limit: int | None = None,
    delay_seconds: float = 0.35,
    fetch_text: Callable[[str], str] = fetch,
    quest_catalog_text: str | None = None,
) -> dict:
    started_at = _utc_now()
    catalog_html = fetch_text(CATALOG_URL)
    catalog_entries, catalog_issue_objects = parse_equipment_catalog_page(
        catalog_html,
        source_url=CATALOG_URL,
    )
    catalog = [entry.to_json() for entry in catalog_entries]
    catalog_issues = [issue.to_json() for issue in catalog_issue_objects]
    catalog_by_id = {int(entry["equipmentId"]): entry for entry in catalog}

    quest_catalog_available = True
    quest_catalog_fetch: dict | None = None
    quest_catalog_issue: dict | None = None
    try:
        if quest_catalog_text is None:
            quest_catalog_text = fetch_text(QUEST_DATA_URL)
            quest_catalog_fetch = _fetch_summary(QUEST_DATA_URL)
        quest_catalog = QuestReferenceCatalog.from_json_text(quest_catalog_text)
    except Exception as exc:
        quest_catalog_available = False
        quest_catalog = QuestReferenceCatalog.empty()
        quest_catalog_issue = {
            "source": SOURCE_ID,
            "kind": "quest-catalog-unavailable",
            "message": f"{type(exc).__name__}: {exc}",
            "sourceUrl": QUEST_DATA_URL,
        }
    ship_catalog = ShipReferenceCatalog.load()

    items = player_equipment_items()
    if equipment_ids is not None:
        selected = {int(value) for value in equipment_ids}
        items = [item for item in items if int(item["api_id"]) in selected]
    if limit is not None:
        items = items[:max(limit, 0)]

    records: list[dict] = []
    issues: list[dict] = list(catalog_issues)
    if quest_catalog_issue:
        issues.append(quest_catalog_issue)
    reference_issues: list[dict] = []
    total = len(items)
    for index, item in enumerate(items, 1):
        equipment_id = int(item["api_id"])
        equipment_name = str(item.get("api_name") or "")
        status = "failed"
        try:
            html, source_url, attempts = _fetch_equipment_page(
                item,
                catalog_by_id,
                fetch_text=fetch_text,
            )
            record, page_issue_objects = parse_equipment_acquisition_page(
                html,
                equipment_id=equipment_id,
                equipment_name=equipment_name,
                source_url=source_url,
            )
            page_reference_issues = resolve_record_references(
                record,
                ships=ship_catalog,
                quests=quest_catalog,
                quest_catalog_available=quest_catalog_available,
            )
            reference_issues.extend(page_reference_issues)
            issues.extend(page_reference_issues)
            record["fetchAttempts"] = attempts
            catalog_entry = catalog_by_id.get(equipment_id)
            if catalog_entry:
                record["catalogEntry"] = catalog_entry
            records.append(record)
            for issue in page_issue_objects:
                issues.append({
                    **issue.to_json(),
                    "equipmentId": equipment_id,
                    "equipmentName": equipment_name,
                    "sourceUrl": source_url,
                })
            status = record["coverageStatus"]
            if delay_seconds > 0 and any(
                attempt.get("validatedInRun") for attempt in attempts
                if attempt.get("status") == "ok"
            ):
                time.sleep(delay_seconds)
        except Exception as exc:
            issues.append({
                "source": SOURCE_ID,
                "kind": "page-fetch-or-parse-failed",
                "message": f"{type(exc).__name__}: {exc}",
                "equipmentId": equipment_id,
                "equipmentName": equipment_name,
            })
        simple_logger.info(
            f"[equipment acquisition] {index}/{total} "
            f"id={equipment_id} name={equipment_name} status={status}"
        )

        if index % 25 == 0 or index == total:
            progress_metadata = build_acquisition_metadata(
                mode="full-diagnostic-crawl",
                started_at=started_at,
                catalog_fetch=_fetch_summary(CATALOG_URL),
                catalog=catalog,
                catalog_issues=catalog_issues,
                selected_items=items,
                records=records,
                issues=issues,
                reference_issues=reference_issues,
                quest_catalog_available=quest_catalog_available,
                quest_catalog_count=len(quest_catalog.records),
                quest_catalog_fetch=quest_catalog_fetch,
            )
            progress_metadata["progress"] = {"completed": index, "total": total}
            write_acquisition_outputs(
                output_dir,
                catalog=catalog,
                records=records,
                issues=issues,
                metadata=progress_metadata,
                reference_issues=reference_issues,
            )

    metadata = build_acquisition_metadata(
        mode="full-diagnostic-crawl",
        started_at=started_at,
        catalog_fetch=_fetch_summary(CATALOG_URL),
        catalog=catalog,
        catalog_issues=catalog_issues,
        selected_items=items,
        records=records,
        issues=issues,
        reference_issues=reference_issues,
        quest_catalog_available=quest_catalog_available,
        quest_catalog_count=len(quest_catalog.records),
        quest_catalog_fetch=quest_catalog_fetch,
    )
    metadata["progress"] = {"completed": total, "total": total}
    write_acquisition_outputs(
        output_dir,
        catalog=catalog,
        records=records,
        issues=issues,
        metadata=metadata,
        reference_issues=reference_issues,
    )
    return metadata



def _format_counts(values: dict | None) -> str:
    values = values or {}
    order = ("resolved", "ambiguous", "unresolved", "catalog-unavailable", "unknown")
    parts = [f"{key}={int(values[key])}" for key in order if key in values]
    parts.extend(
        f"{key}={int(value)}"
        for key, value in sorted(values.items())
        if key not in order
    )
    return ", ".join(parts) if parts else "none"


def print_summary(metadata: dict) -> None:
    print("装备获取方式全量诊断完成")
    print(
        "- 页面："
        f"selected={metadata.get('selectedEquipmentCount', 0)}, "
        f"records={metadata.get('recordCount', 0)}, "
        f"accepted={metadata.get('acceptedRecordCount', 0)}, "
        f"missing={metadata.get('missingRecordCount', 0)}"
    )
    print(
        "- 页面/解析异常："
        f"{metadata.get('issueCount', 0)}；"
        f"{_format_counts(metadata.get('issueKindCounts'))}"
    )
    print(
        "- 舰娘引用："
        f"total={metadata.get('shipReferenceCount', 0)}；"
        f"{_format_counts(metadata.get('shipReferenceStatusCounts'))}"
    )
    print(
        "- 任务引用："
        f"total={metadata.get('questReferenceCount', 0)}；"
        f"{_format_counts(metadata.get('questReferenceStatusCounts'))}"
    )
    print(
        "- 引用异常："
        f"{metadata.get('referenceIssueCount', 0)}；"
        f"{_format_counts(metadata.get('referenceIssueKindCounts'))}"
    )
    print(f"- 未分类证据：{metadata.get('unclassifiedEvidenceCount', 0)}")
    print(f"- 任务目录可用：{str(bool(metadata.get('questCatalogAvailable'))).lower()}")
    print(f"- 正式 drop-from 已改变：{str(bool(metadata.get('canonicalDataChanged'))).lower()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Crawl all player equipment detail pages from WikiWiki and export "
            "diagnostic acquisition evidence without changing canonical data"
        )
    )
    parser.add_argument(
        "--equipment-id",
        action="append",
        type=int,
        dest="equipment_ids",
        help="restrict to a Start2 equipment ID; repeat for multiple IDs",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--json", action="store_true", help="print metadata as JSON")
    args = parser.parse_args()
    metadata = run_full_crawl(
        output_dir=args.output_dir,
        equipment_ids=args.equipment_ids,
        limit=args.limit,
        delay_seconds=max(args.delay, 0.0),
    )
    if args.json:
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
    else:
        print_summary(metadata)


if __name__ == "__main__":
    main()
