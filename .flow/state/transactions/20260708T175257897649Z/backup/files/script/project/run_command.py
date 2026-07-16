from __future__ import annotations

import json
from pathlib import Path

from .command_support import result, run_logged


def _reliability_completed_lines(report_path: Path) -> list[str]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["来源权重摘要：未能读取数据报告"]
    reliability = report.get("sourceReliability")
    if not isinstance(reliability, dict):
        return ["来源权重摘要：数据报告未包含权重结果"]
    sources = reliability.get("sources")
    if not isinstance(sources, list) or not sources:
        return ["来源权重摘要：暂无可比较来源"]
    values = []
    for row in sources:
        if not isinstance(row, dict):
            continue
        try:
            weight = float(row.get("relativeWeight", 1.0))
        except (TypeError, ValueError):
            weight = 1.0
        values.append(
            f"{row.get('source', 'unknown')}={weight:.4f}/{row.get('confidence', 'low')}"
        )
    if not values:
        return ["来源权重摘要：暂无有效权重记录"]
    return [
        "来源权重（仅观察，不参与正式数据选举）：" + "，".join(values),
        "来源权重明细：dist/data-pipeline/sources/reliability/report.md",
    ]


def run(root: Path, args: list[str], config: dict, loader=None):
    report_path = root / "dist/data-pipeline/local-validation.json"
    before_log = run_logged(
        root,
        ["{python}", "script/project/python_runner.py", "script/project/check.py", "before"],
        "run-before-check",
    )
    command = [
        "{python}", "script/project/python_runner.py",
        "script/project/data_pipeline.py",
        "--report", str(report_path.relative_to(root)),
    ]
    log = run_logged(root, command, "data-validate")
    completed = [
        f"before check：{before_log.relative_to(root)}",
        f"日志：{log.relative_to(root)}",
        f"数据报告：{report_path.relative_to(root)}",
        *_reliability_completed_lines(report_path),
    ]
    return result(
        "成功",
        "严格 Spider 数据流程通过",
        completed,
        [],
        "检查数据差异后执行 ./flow push",
        "Git 可恢复生成数据",
    )
