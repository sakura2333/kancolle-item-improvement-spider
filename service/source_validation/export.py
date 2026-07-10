from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Iterable, List

from configs.path import get_data_pipeline_dir
from service.source_validation.compare import ScheduleDiff
from service.source_validation.model import SourceResult
from util.json_utils import write_json, write_json_lines


def source_root() -> str:
    return get_data_pipeline_dir("sources")


def _safe_source_name(source: str) -> str:
    return source.replace("/", "-").replace("_", "-")


def export_source(result: SourceResult):
    directory = os.path.join(source_root(), _safe_source_name(result.source))
    os.makedirs(directory, exist_ok=True)
    schedule_rows = [schedule.to_json() for schedule in result.schedules]
    # Keep the original file name for compatibility and also expose the clearer
    # intermediate-data names used by the AI review pipeline.
    write_json_lines(
        os.path.join(directory, "schedules.nedb"),
        schedule_rows,
        mode="w",
        log=True,
    )
    write_json_lines(
        os.path.join(directory, "normalized-facts.nedb"),
        schedule_rows,
        mode="w",
        log=True,
    )
    write_json_lines(
        os.path.join(directory, "parsed-rules.nedb"),
        [row for row in schedule_rows if row.get("rawText") or row.get("evidence")],
        mode="w",
        log=True,
    )
    write_json_lines(
        os.path.join(directory, "issues.nedb"),
        [issue.to_json() for issue in result.issues],
        mode="w",
        log=True,
    )
    write_json(
        os.path.join(directory, "metadata.json"),
        result.to_metadata_json(),
        mode="w",
        log=True,
    )


def export_comparison(
    baseline: SourceResult,
    candidates: List[SourceResult],
    diffs: List[ScheduleDiff],
    summaries: List[dict],
):
    directory = os.path.join(source_root(), "comparison")
    os.makedirs(directory, exist_ok=True)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "baseline": baseline.source,
        "sources": summaries,
    }
    write_json(os.path.join(directory, "summary.json"), payload, mode="w", log=True)
    write_json_lines(
        os.path.join(directory, "differences.nedb"),
        [diff.to_json() for diff in diffs],
        mode="w",
        log=True,
    )

    lines = [
        "# Improvement source comparison",
        "",
        f"Generated: {generated_at}",
        f"Baseline: `{baseline.source}`",
        "",
        "| Source | Status | Capabilities | Comparable | Match | Week mismatch | Missing | Extra | Ignored unsupported | Issues | Agreement |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        agreement = summary.get("agreementRate")
        agreement_text = "-" if agreement is None else f"{agreement:.2%}"
        lines.append(
            "| {source} | {status} | {capabilities} | {comparableScheduleCount} | {matchCount} | "
            "{weekdayMismatchCount} | {missingInCandidateCount} | "
            "{extraInCandidateCount} | {ignoredUnsupportedCapabilityCount} | "
            "{candidateIssueCount} | {agreement} |".format(
                agreement=agreement_text,
                capabilities=", ".join(summary.get("supportedCapabilities", [])) or "-",
                **summary,
            )
        )
    lines.extend([
        "",
        "`differences.nedb` contains the non-matching equipment/helper schedules.",
        "A missing or extra record is evidence for review, not an automatic correction.",
        "Capabilities not implemented by a candidate adapter are excluded from Missing and counted as Ignored unsupported.",
        "The canonical files in `dist/data-pipeline/improvement/` remain generated only from Akashi List.",
        "",
    ])
    with open(os.path.join(directory, "report.md"), "w", encoding="utf-8") as file:
        file.write("\n".join(lines))
