#!/usr/bin/env python3
from __future__ import annotations

"""Migrate existing crawler HTML into the shared raw HTTP cache.

This is a one-time/manual compatibility tool.  It consumes the crawler's
``records.json`` so every numeric HTML file keeps its original URL identity.
The source files are preserved by default; pass ``--remove-source`` only after
reviewing a successful migration.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raw_cache import (
    cache_key,
    install_capture,
    sha256_file,
    url_to_cache_path,
    write_json_atomic,
)

DEFAULT_SOURCE = Path(".flow/local/wikiwiki-crawler")
DEFAULT_RAW_ROOT = Path(".flow/local/source-cache")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def resolve_project_path(project: Path, value: Path) -> Path:
    return value.resolve() if value.is_absolute() else (project / value).resolve()


def source_html_path(project: Path, source_root: Path, record: dict[str, Any]) -> Path:
    equipment_id = int(record["equipmentId"])
    primary = source_root / "raw" / f"{equipment_id}.html"
    if primary.is_file():
        return primary
    raw_path = str(record.get("rawPath") or "").strip()
    if raw_path:
        candidate = Path(raw_path)
        candidates = [candidate] if candidate.is_absolute() else [project / candidate, source_root / candidate]
        for path in candidates:
            if path.is_file():
                return path.resolve()
    return primary


def relative_or_absolute(path: Path, project: Path) -> str:
    try:
        return path.resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def migrate(args: argparse.Namespace) -> int:
    project = args.project.resolve()
    source_root = resolve_project_path(project, args.source)
    raw_root = resolve_project_path(project, args.raw_root)
    records_path = source_root / "records.json"
    if not records_path.is_file():
        raise FileNotFoundError(f"crawler records not found: {records_path}")
    payload = read_json(records_path)
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, dict):
        raise ValueError(f"invalid crawler records: {records_path}")

    counts = {
        "selected": 0,
        "installed": 0,
        "replaced": 0,
        "alreadyPresent": 0,
        "missing": 0,
        "invalid": 0,
        "conflicts": 0,
        "sourceRemoved": 0,
    }
    results: list[dict[str, Any]] = []

    def sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, str]:
        try:
            return int(item[1].get("equipmentId") or item[0]), item[0]
        except (TypeError, ValueError):
            return 10**9, item[0]

    for key, record in sorted(records.items(), key=sort_key):
        if not isinstance(record, dict) or not str(record.get("status") or "").startswith("saved"):
            continue
        counts["selected"] += 1
        try:
            equipment_id = int(record.get("equipmentId") or key)
            url = str(record.get("url") or "").strip()
            if not url:
                raise ValueError("record URL is empty")
            source_path = source_html_path(project, source_root, record)
            if not source_path.is_file():
                counts["missing"] += 1
                results.append({
                    "equipmentId": equipment_id,
                    "status": "missing-source",
                    "sourcePath": str(source_path),
                    "url": url,
                })
                print(f"id={equipment_id} status=missing-source path={source_path}")
                continue
            expected = str(record.get("sha256") or "").strip() or None
            actual = sha256_file(source_path)
            if expected and expected != actual:
                counts["invalid"] += 1
                results.append({
                    "equipmentId": equipment_id,
                    "status": "sha256-mismatch",
                    "sourcePath": str(source_path),
                    "expectedSha256": expected,
                    "actualSha256": actual,
                    "url": url,
                })
                print(f"id={equipment_id} status=sha256-mismatch")
                continue

            target_path = url_to_cache_path(raw_root, url)
            if args.dry_run:
                target_status = "would-install"
                if target_path.is_file():
                    target_status = "already-present" if sha256_file(target_path) == actual else "would-conflict"
                results.append({
                    "equipmentId": equipment_id,
                    "status": target_status,
                    "sourcePath": str(source_path),
                    "targetPath": str(target_path),
                    "url": url,
                    "sha256": actual,
                })
                print(f"id={equipment_id} status={target_status} target={target_path}")
                if target_status == "would-conflict":
                    counts["conflicts"] += 1
                continue

            try:
                target_path, status, digest = install_capture(
                    source_path,
                    raw_root=raw_root,
                    url=url,
                    fetched_at=str(record.get("fetchedAt") or "") or None,
                    http_code=int(record.get("httpCode") or 200),
                    expected_sha256=expected,
                    overwrite=args.overwrite,
                    remove_source=args.remove_source,
                    capture_metadata={
                        "equipmentId": equipment_id,
                        "equipmentName": str(record.get("equipmentName") or ""),
                        "urlSource": str(record.get("urlSource") or "migration-record"),
                        "sourcePageNumber": record.get("sourcePageNumber", record.get("observedPageId")),
                    },
                )
            except FileExistsError as exc:
                counts["conflicts"] += 1
                results.append({
                    "equipmentId": equipment_id,
                    "status": "conflict",
                    "sourcePath": str(source_path),
                    "targetPath": str(target_path),
                    "url": url,
                    "message": str(exc),
                })
                print(f"id={equipment_id} status=conflict target={target_path}")
                continue

            count_key = {
                "installed": "installed",
                "replaced": "replaced",
                "already-present": "alreadyPresent",
            }[status]
            counts[count_key] += 1
            if args.remove_source and not source_path.exists():
                counts["sourceRemoved"] += 1
            old_raw_path = record.get("rawPath")
            new_raw_path = relative_or_absolute(target_path, project)
            if old_raw_path and old_raw_path != new_raw_path:
                record.setdefault("legacyRawPath", old_raw_path)
            record.update({
                "rawPath": new_raw_path,
                "rawCacheKey": cache_key(raw_root, target_path),
                "bytes": target_path.stat().st_size,
                "sha256": digest,
            })
            results.append({
                "equipmentId": equipment_id,
                "status": status,
                "sourcePath": str(source_path),
                "targetPath": str(target_path),
                "url": url,
                "sha256": digest,
            })
            print(f"id={equipment_id} status={status} target={target_path}")
        except (OSError, TypeError, ValueError) as exc:
            counts["invalid"] += 1
            results.append({
                "recordKey": key,
                "status": "invalid-record",
                "message": f"{type(exc).__name__}: {exc}",
            })
            print(f"record={key} status=invalid-record error={exc}")

    summary = {
        "schemaVersion": 1,
        "mode": "wikiwiki-raw-cache-migration",
        "generatedAt": utc_now(),
        "project": str(project),
        "sourceRoot": str(source_root),
        "rawRoot": str(raw_root),
        "dryRun": bool(args.dry_run),
        "removeSource": bool(args.remove_source),
        "overwrite": bool(args.overwrite),
        **counts,
        "results": results,
    }
    if not args.dry_run:
        payload["records"] = records
        payload["schemaVersion"] = max(int(payload.get("schemaVersion") or 1), 1)
        write_json_atomic(records_path, payload)
        write_json_atomic(source_root / "migration-summary.json", summary)

    print("WikiWiki raw cache migration summary")
    for key in (
        "selected", "installed", "replaced", "alreadyPresent", "missing",
        "invalid", "conflicts", "sourceRemoved",
    ):
        print(f"- {key}: {counts[key]}")
    print(f"- dryRun: {str(bool(args.dry_run)).lower()}")
    print(f"- rawRoot: {raw_root}")
    return 1 if counts["missing"] or counts["invalid"] or counts["conflicts"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate existing WikiWiki crawler HTML into .flow/local/source-cache"
    )
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--remove-source",
        action="store_true",
        help="remove old HTML only after the target copy and SHA-256 verification succeed",
    )
    return parser


def main() -> int:
    try:
        return migrate(build_parser().parse_args())
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
