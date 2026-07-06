from __future__ import annotations

"""Offline WikiWiki equipment-acquisition parser over the shared raw cache.

The parser never performs network I/O and never reads crawler-private state.
Captured pages are discovered through ``data/raw_data/site_cache/_meta.json``;
this is the same raw evidence store used by the project's HTTP cache layer.
"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from configs.path import PROJECT_ROOT, get_data_dir
from service.data_package.acquisition_references import (
    QUEST_DATA_URL,
    QuestReferenceCatalog,
    ShipReferenceCatalog,
    resolve_record_references,
)
from service.operator_stop import (
    OperatorStopError,
    write_operator_stop,
    write_operator_stop_files,
)
from service.data_package.equipment_acquisition import (
    SOURCE_ID,
    parse_equipment_acquisition_page,
)
from service.data_package.equipment_acquisition_crawl import (
    DEFAULT_OUTPUT_DIR,
    player_equipment_items,
    build_acquisition_metadata,
    print_summary,
    write_acquisition_outputs,
)
from util.logger import simple_logger

DEFAULT_RAW_ROOT = Path(get_data_dir("raw_data")) / "site_cache"
CAPTURE_SOURCE = "external-browser-session-crawl"




def _portable_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(PROJECT_ROOT).resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_meta_index(raw_root: Path) -> dict[str, dict[str, Any]]:
    path = raw_root / "_meta.json"
    if not path.is_file():
        raise FileNotFoundError(f"raw cache metadata not found: {path}")
    payload = json.loads(path.read_text("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"raw cache metadata must be an object: {path}")
    return {
        str(key): value
        for key, value in payload.items()
        if isinstance(value, dict)
    }


def _capture_catalog(
    raw_root: Path,
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    captures: dict[int, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    for cache_key, meta in _read_meta_index(raw_root).items():
        if meta.get("acquisition_source") != CAPTURE_SOURCE:
            continue
        try:
            equipment_id = int(meta.get("equipmentId") or 0)
        except (TypeError, ValueError):
            equipment_id = 0
        if equipment_id <= 0:
            issues.append({
                "source": SOURCE_ID,
                "kind": "raw-capture-missing-equipment-id",
                "message": "raw cache capture has no valid equipmentId",
                "cacheKey": cache_key,
                "sourceUrl": meta.get("url"),
            })
            continue
        candidate = {"cacheKey": cache_key, **meta}
        previous = captures.get(equipment_id)
        if previous is not None:
            previous_at = int(previous.get("validated_at") or previous.get("fetched_at") or 0)
            candidate_at = int(candidate.get("validated_at") or candidate.get("fetched_at") or 0)
            chosen = candidate if candidate_at >= previous_at else previous
            rejected = previous if chosen is candidate else candidate
            captures[equipment_id] = chosen
            issues.append({
                "source": SOURCE_ID,
                "kind": "duplicate-raw-capture",
                "message": "multiple raw cache pages declare the same equipmentId; newest capture selected",
                "equipmentId": equipment_id,
                "selectedCacheKey": chosen["cacheKey"],
                "rejectedCacheKey": rejected["cacheKey"],
            })
        else:
            captures[equipment_id] = candidate
    return captures, issues


def _safe_cache_path(raw_root: Path, cache_key: str) -> Path:
    target = (raw_root / cache_key).resolve()
    root = raw_root.resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"raw cache key escapes root: {cache_key}")
    return target


def _load_quest_catalog(
    raw_root: Path,
    meta_index: dict[str, dict[str, Any]],
    *,
    quest_catalog_path: Path | None,
    quest_catalog_text: str | None,
) -> tuple[QuestReferenceCatalog, bool, dict[str, Any] | None, dict[str, Any] | None]:
    source_info: dict[str, Any] | None = None
    try:
        if quest_catalog_text is not None:
            return QuestReferenceCatalog.from_json_text(quest_catalog_text), True, {
                "mode": "provided-text",
                "url": QUEST_DATA_URL,
            }, None
        if quest_catalog_path is not None:
            path = quest_catalog_path.resolve()
            text = path.read_text("utf-8")
            return QuestReferenceCatalog.from_json_text(text), True, {
                "mode": "provided-file",
                "path": str(path),
                "url": QUEST_DATA_URL,
            }, None
        for cache_key, meta in meta_index.items():
            if str(meta.get("url") or "") != QUEST_DATA_URL:
                continue
            path = _safe_cache_path(raw_root, cache_key)
            text = path.read_text("utf-8")
            source_info = {
                "mode": "raw-cache",
                "path": str(path),
                "cachePath": cache_key,
                "url": QUEST_DATA_URL,
                "contentSha256": meta.get("content_sha256"),
            }
            return QuestReferenceCatalog.from_json_text(text), True, source_info, None
        raise FileNotFoundError("quest catalog is not present in the raw cache")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        issue = {
            "source": SOURCE_ID,
            "kind": "quest-catalog-unavailable",
            "message": f"{type(exc).__name__}: {exc}",
            "sourceUrl": QUEST_DATA_URL,
        }
        return QuestReferenceCatalog.empty(), False, source_info, issue


def run_offline_parse(
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    equipment_ids: Iterable[int] | None = None,
    limit: int | None = None,
    quest_catalog_path: Path | None = None,
    quest_catalog_text: str | None = None,
    allow_incomplete: bool = False,
) -> dict[str, Any]:
    started_at = _utc_now()
    raw_root = raw_root.resolve()
    meta_index = _read_meta_index(raw_root)
    captures, capture_issues = _capture_catalog(raw_root)
    operator_stops: list[OperatorStopError] = []
    for issue in capture_issues:
        if issue.get("kind") == "duplicate-raw-capture":
            selected = captures.get(int(issue.get("equipmentId") or 0), {})
            selected_sha = str(selected.get("content_sha256") or "")
            rejected_key = str(issue.get("rejectedCacheKey") or "")
            rejected = meta_index.get(rejected_key, {})
            rejected_sha = str(rejected.get("content_sha256") or "")
            if selected_sha and rejected_sha and selected_sha != rejected_sha:
                operator_stops.append(OperatorStopError(
                    stop_reason="raw-cache-sha-conflict",
                    message=f"同一装备存在内容不同的原始页面：{issue.get('equipmentId')}",
                    action="人工检查两个 raw cache 页面并保留正确证据，再更新 _meta.json。",
                    checkpoint=str(raw_root / "_meta.json"),
                    details=issue,
                ))
    quest_catalog, quest_available, quest_source, quest_issue = _load_quest_catalog(
        raw_root,
        meta_index,
        quest_catalog_path=quest_catalog_path,
        quest_catalog_text=quest_catalog_text,
    )
    ship_catalog = ShipReferenceCatalog.load()

    items = player_equipment_items()
    if equipment_ids is not None:
        selected = {int(value) for value in equipment_ids}
        items = [item for item in items if int(item["api_id"]) in selected]
    if limit is not None:
        items = items[: max(int(limit), 0)]

    catalog = [
        {
            "equipmentId": equipment_id,
            "equipmentName": str(meta.get("equipmentName") or ""),
            "sourceUrl": str(meta.get("url") or ""),
            "cacheKey": str(meta["cacheKey"]),
            "contentSha256": meta.get("content_sha256"),
            "fetchedAt": meta.get("fetched_at"),
        }
        for equipment_id, meta in sorted(captures.items())
    ]
    issues: list[dict[str, Any]] = list(capture_issues)
    if quest_issue:
        issues.append(quest_issue)
        operator_stops.append(OperatorStopError(
            stop_reason="quest-catalog-invalid",
            message=quest_issue["message"],
            action="获取并校验 kcwikizh/kcQuests 的 quests-scn.json 后重试。",
            checkpoint=str(output_dir),
            details={"sourceUrl": QUEST_DATA_URL},
        ))
    reference_issues: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    parsed_status = Counter()

    total = len(items)
    for index, item in enumerate(items, 1):
        equipment_id = int(item["api_id"])
        equipment_name = str(item.get("api_name") or "")
        capture = captures.get(equipment_id)
        current_status = "missing"
        if capture is None:
            issues.append({
                "source": SOURCE_ID,
                "kind": "raw-page-missing",
                "message": "no external browser-session capture is registered for this Start2 equipment",
                "equipmentId": equipment_id,
                "equipmentName": equipment_name,
            })
            parsed_status["missing"] += 1
            continue

        cache_key = str(capture["cacheKey"])
        source_url = str(capture.get("url") or "")
        try:
            raw_path = _safe_cache_path(raw_root, cache_key)
            if not raw_path.is_file():
                raise FileNotFoundError(raw_path)
            expected_sha = str(capture.get("content_sha256") or "").strip()
            actual_sha = _sha256(raw_path)
            if expected_sha and expected_sha != actual_sha:
                raise ValueError(
                    f"raw page sha256 mismatch expected={expected_sha} actual={actual_sha}"
                )
            html = raw_path.read_text("utf-8", errors="replace")
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
                quest_catalog_available=quest_available,
            )
            reference_issues.extend(page_reference_issues)
            issues.extend(page_reference_issues)
            for reference_issue in page_reference_issues:
                if reference_issue.get("kind") in {
                    "quest-reference-ambiguous", "ship-reference-ambiguous"
                }:
                    operator_stops.append(OperatorStopError(
                        stop_reason=reference_issue["kind"],
                        message=reference_issue["message"],
                        action="人工确认唯一 canonical ID，并补充名称映射或修正来源证据。",
                        checkpoint=str(output_dir),
                        details=reference_issue,
                    ))
            for issue in page_issue_objects:
                issues.append({
                    **issue.to_json(),
                    "equipmentId": equipment_id,
                    "equipmentName": equipment_name,
                    "sourceUrl": source_url,
                    "cacheKey": cache_key,
                })
            record["rawEvidence"] = {
                "cacheKey": cache_key,
                "rawPath": _portable_path(raw_path),
                "contentSha256": actual_sha,
                "fetchedAt": capture.get("fetched_at"),
                "validatedAt": capture.get("validated_at"),
                "acquisitionSource": capture.get("acquisition_source"),
            }
            record["fetchAttempts"] = [{
                "candidateSource": "raw-cache",
                "status": "ok",
                "url": source_url,
                "cachePath": cache_key,
                "contentSha256": actual_sha,
            }]
            records.append(record)
            current_status = str(record.get("coverageStatus", "unknown"))
            parsed_status[current_status] += 1
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issue_kind = (
                "raw-cache-sha-conflict"
                if "sha256 mismatch" in str(exc)
                else "raw-page-read-or-parse-failed"
            )
            issue = {
                "source": SOURCE_ID,
                "kind": issue_kind,
                "message": f"{type(exc).__name__}: {exc}",
                "equipmentId": equipment_id,
                "equipmentName": equipment_name,
                "sourceUrl": source_url,
                "cacheKey": cache_key,
            }
            issues.append(issue)
            if issue_kind == "raw-cache-sha-conflict":
                operator_stops.append(OperatorStopError(
                    stop_reason=issue_kind,
                    message=issue["message"],
                    action="不要覆盖原始证据；人工核对页面与 _meta.json 的 SHA-256 后修复。",
                    checkpoint=str(raw_root / "_meta.json"),
                    details=issue,
                ))
            current_status = "failed"
            parsed_status[current_status] += 1
        simple_logger.info(
            f"[equipment acquisition offline] {index}/{total} "
            f"id={equipment_id} name={equipment_name} status={current_status}"
        )

    simple_logger.info(
        "[equipment acquisition offline] page parsing complete; "
        f"records={len(records)} issues={len(issues)} "
        f"referenceIssues={len(reference_issues)}"
    )
    simple_logger.info(
        "[equipment acquisition offline] building metadata and output datasets"
    )
    metadata = build_acquisition_metadata(
        mode="offline-raw-cache-parse",
        started_at=started_at,
        catalog_fetch=None,
        catalog=catalog,
        catalog_issues=capture_issues,
        selected_items=items,
        records=records,
        issues=issues,
        reference_issues=reference_issues,
        quest_catalog_available=quest_available,
        quest_catalog_count=len(quest_catalog.records),
        quest_catalog_fetch=quest_source,
    )
    metadata.update({
        "rawRoot": _portable_path(raw_root),
        "rawCaptureCount": len(captures),
        "selectedRawCaptureCount": sum(
            1 for item in items if int(item["api_id"]) in captures
        ),
        "missingRawCaptureCount": sum(
            1 for item in items if int(item["api_id"]) not in captures
        ),
        "rawCaptureIssueCount": len(capture_issues),
        "parseStatusCounts": dict(sorted(parsed_status.items())),
        "questCatalogSource": quest_source,
        "networkAccess": False,
        "progress": {"completed": total, "total": total},
    })
    simple_logger.info(
        "[equipment acquisition offline] writing acquisition records, diagnostics, and metadata"
    )
    write_acquisition_outputs(
        output_dir,
        catalog=catalog,
        records=records,
        issues=issues,
        metadata=metadata,
        reference_issues=reference_issues,
    )
    primary_stop, unique_operator_stops = write_operator_stop_files(
        operator_stops,
        output_dir=output_dir,
    )
    simple_logger.info(
        "[equipment acquisition offline] output write complete; "
        f"operatorStops={len(unique_operator_stops)}"
    )
    if primary_stop is not None and not allow_incomplete:
        primary_stop.details = {
            **primary_stop.details,
            "outputDir": str(output_dir),
        }
        # This ERROR is intentionally emitted through the colored logger so it
        # remains visibly red when Flow replays the failing log tail.
        simple_logger.error(
            "[equipment acquisition offline] strict operator-stop gate rejected "
            f"the dataset; stopReason={primary_stop.stop_reason}; "
            f"operatorStops={len(unique_operator_stops)}; "
            f"diagnostics={output_dir / 'operator-stops.nedb'}"
        )
        raise primary_stop
    if primary_stop is not None:
        simple_logger.warning(
            "[equipment acquisition offline] operator stops retained because "
            "allow_incomplete=true"
        )
    else:
        simple_logger.info(
            "[equipment acquisition offline] strict reference gate passed"
        )
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse WikiWiki equipment acquisition evidence from the local raw cache only"
    )
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--equipment-id", action="append", type=int, dest="equipment_ids")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--quest-catalog", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        metadata = run_offline_parse(
            raw_root=args.raw_root,
            output_dir=args.output_dir,
            equipment_ids=args.equipment_ids,
            limit=args.limit,
            quest_catalog_path=args.quest_catalog,
            allow_incomplete=args.allow_incomplete,
        )
    except OperatorStopError as exc:
        write_operator_stop(exc, color=True)
        return exc.exit_code
    if args.json:
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
    else:
        print_summary(metadata)
        print(f"- 原始捕获：{metadata.get('rawCaptureCount', 0)}")
        print(f"- 缺失捕获：{metadata.get('missingRawCaptureCount', 0)}")
        print("- 网络访问：false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
