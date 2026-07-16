#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from _common import (
    PACKAGE_DIR,
    PROJECT_ROOT,
    ProjectCommandError,
    main_guard,
    parse_json_output,
    project_env,
    require_tool,
    run,
    write_json,
)


RELIABILITY_SUMMARY_PATH = (
    PROJECT_ROOT / "dist" / "data-pipeline" / "sources" / "reliability" / "summary.json"
)
WIKIWIKI_SOURCE_RECEIPT_PATH = (
    PROJECT_ROOT / ".flow" / "local" / "wikiwiki-crawler" / "source-receipt.json"
)

FORBIDDEN_GENERATED_WORKTREE_PREFIXES = (
    "data/raw_data/",
    "data/sources/",
    "data/improvement/",
    "packages/kancolle-data/audit/",
    "packages/kancolle-data/compat/",
    "packages/kancolle-data/equipment/",
    "packages/kancolle-data/improvement/",
    "packages/kancolle-data/assets/",
)
FORBIDDEN_GENERATED_WORKTREE_PATHS = {
    "packages/kancolle-data/manifest.json",
    "packages/kancolle-data/CHANGELOG.md",
    "packages/kancolle-data/RELEASES.json",
}


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)



def verify_wikiwiki_source_receipt(path: Path = WIKIWIKI_SOURCE_RECEIPT_PATH) -> dict:
    if not path.is_file():
        raise ProjectCommandError(
            "WikiWiki source acquisition receipt is missing; "
            "run ./flow wikiwiki before ./flow run"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectCommandError(f"WikiWiki source acquisition receipt is unreadable: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ProjectCommandError("WikiWiki source acquisition receipt has invalid schema")
    if payload.get("source") != "wikiwiki-jp":
        raise ProjectCommandError("WikiWiki source acquisition receipt source mismatch")
    indexes = payload.get("indexes") if isinstance(payload.get("indexes"), dict) else {}
    required = ["ship", "equipment", "improvement"]
    missing = []
    not_ready = []
    for kind in required:
        entry = indexes.get(kind) if isinstance(indexes, dict) else None
        if not isinstance(entry, dict):
            missing.append(kind)
            continue
        if entry.get("status") != "ready":
            not_ready.append(f"{kind}:{entry.get('status') or 'unknown'}")

    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    equipment_details = details.get("equipment") if isinstance(details, dict) else None
    ship_details = details.get("ship") if isinstance(details, dict) else None
    detail_not_ready = []
    if not isinstance(equipment_details, dict):
        detail_not_ready.append("equipment:missing")
    elif equipment_details.get("status") != "ready":
        detail_not_ready.append(
            "equipment:"
            + str(equipment_details.get("status") or "unknown")
            + f" remaining={equipment_details.get('remaining', 'unknown')}"
            + f" failed={equipment_details.get('failed', 'unknown')}"
            + f" stopReason={equipment_details.get('stopReason') or 'none'}"
        )
    if not isinstance(ship_details, dict):
        detail_not_ready.append("ship:missing")
    elif ship_details.get("status") not in {"deferred", "ready"}:
        detail_not_ready.append("ship:" + str(ship_details.get("status") or "unknown"))

    if missing or not_ready or detail_not_ready or payload.get("ready") is not True:
        detail = []
        if missing:
            detail.append("missingIndexes=" + ",".join(missing))
        if not_ready:
            detail.append("notReadyIndexes=" + ",".join(not_ready))
        if detail_not_ready:
            detail.append("notReadyDetails=" + ",".join(detail_not_ready))
        raise ProjectCommandError(
            "WikiWiki source acquisition receipt is not ready; "
            + "; ".join(detail)
            + "; run ./flow wikiwiki --full to refresh ship/equipment/improvement indexes and required equipment details"
        )
    return payload


def load_reliability_observation(path: Path = RELIABILITY_SUMMARY_PATH) -> dict:
    if not path.is_file():
        raise ProjectCommandError(f"缺少来源权重摘要：{_display_path(path)}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectCommandError(f"来源权重摘要不可读：{exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise ProjectCommandError("来源权重摘要结构无效")
    if payload.get("applyToCanonicalElection") is not False:
        raise ProjectCommandError("来源权重不得参与正式数据选举")

    sources = []
    for row in payload["sources"]:
        if not isinstance(row, dict):
            raise ProjectCommandError("来源权重摘要包含无效来源记录")
        source = str(row.get("source", "")).strip()
        if not source:
            raise ProjectCommandError("来源权重摘要包含空来源名称")
        history = row.get("history") if isinstance(row.get("history"), dict) else {}
        sources.append({
            "source": source,
            "relativeWeight": float(row.get("relativeWeight", 1.0)),
            "confidence": str(row.get("confidence", "low")),
            "weightStatus": str(row.get("weightStatus", "insufficient-evidence")),
            "currentConsistencyScore": row.get("currentConsistencyScore"),
            "historyAppliedToWeight": bool(row.get("historyAppliedToWeight", False)),
            "historyEventCount": int(history.get("eventCount", 0) or 0),
        })
    return {
        "mode": str(payload.get("mode", "advisory")),
        "generatedAt": payload.get("generatedAt"),
        "applyToCanonicalElection": False,
        "canonicalElectionUnchanged": bool(payload.get("canonicalElectionUnchanged", True)),
        "sources": sources,
    }


def _git_dirty_paths() -> list[str]:
    completed = run(
        ["git", "status", "--short"],
        cwd=PROJECT_ROOT,
        env=project_env(),
        capture_output=True,
    )
    result = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        # porcelain v1: XY PATH, or XY OLD -> NEW
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        result.append(path)
    return result


def verify_forbidden_generated_dirty_paths() -> None:
    dirty = []
    for path in _git_dirty_paths():
        if path in FORBIDDEN_GENERATED_WORKTREE_PATHS or any(
            path.startswith(prefix) for prefix in FORBIDDEN_GENERATED_WORKTREE_PREFIXES
        ):
            dirty.append(path)
    if dirty:
        lines = "\n".join(f"- {path}" for path in dirty)
        raise ProjectCommandError(f"旧生成路径被写脏：\n{lines}")


def reliability_log_lines(observation: dict) -> list[str]:
    lines = [
        "[source reliability] advisory-only; canonical election unchanged",
    ]
    for row in observation.get("sources", []):
        score = row.get("currentConsistencyScore")
        score_text = "n/a" if score is None else f"{float(score):.6f}"
        lines.append(
            "[source reliability] "
            f"source={row['source']}, "
            f"weight={float(row['relativeWeight']):.4f}, "
            f"confidence={row['confidence']}, "
            f"currentConsistency={score_text}, "
            f"historyEvents={int(row['historyEventCount'])}, "
            f"historyApplied={str(bool(row['historyAppliedToWeight'])).lower()}"
        )
    return lines


def execute(report_path: Path) -> None:
    npm = require_tool("npm")
    env = project_env({"DATA_PACKAGE_STRICT": "1", "VALIDATION_STRICT": "1"})

    receipt = verify_wikiwiki_source_receipt()
    print(
        "[wikiwiki source gate] "
        "ready=true indexes=" + ",".join(receipt["requiredIndexes"]),
        flush=True,
    )

    run(
        [sys.executable, "-m", "service.data_package.cli", "build", "--strict"],
        cwd=PROJECT_ROOT,
        env=env,
    )
    run([npm, "run", "check"], cwd=PACKAGE_DIR, env=env)
    run([npm, "run", "check:fresh"], cwd=PACKAGE_DIR, env=env)
    run([sys.executable, "script/project/check.py", "after"], cwd=PROJECT_ROOT, env=env)
    verify_forbidden_generated_dirty_paths()
    packed = run(
        [npm, "pack", "--dry-run", "--json"],
        cwd=PACKAGE_DIR,
        env=env,
        capture_output=True,
    )
    pack_result = parse_json_output(packed.stdout)
    if not isinstance(pack_result, list) or len(pack_result) != 1:
        raise ProjectCommandError("npm pack --dry-run did not return exactly one artifact")

    manifest = json.loads((PACKAGE_DIR / "manifest.json").read_text(encoding="utf-8"))
    reliability = load_reliability_observation()
    report = {
        "schemaVersion": 1,
        "status": "passed",
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "mode": "local-strict-validation",
        "packageVersion": manifest.get("packageVersion"),
        "datasetCount": len(manifest.get("datasets", {})),
        "npmPack": pack_result[0],
        "sourceReliability": reliability,
    }
    write_json(report_path, report)
    for line in reliability_log_lines(reliability):
        print(line, flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="本地运行严格 Spider 主流程并验证 npm 数据包")
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "dist" / "data-pipeline" / "local-validation.json",
    )
    args = parser.parse_args()
    report = args.report if args.report.is_absolute() else PROJECT_ROOT / args.report
    return main_guard(lambda: execute(report))


if __name__ == "__main__":
    raise SystemExit(main())
