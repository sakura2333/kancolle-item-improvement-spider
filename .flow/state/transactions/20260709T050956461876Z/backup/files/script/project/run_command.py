from __future__ import annotations

import json
from pathlib import Path

from .command_support import result, run_logged
from .source_phase import SourceTask, run_source_tasks
from .wikiwiki_receipt import summary as wikiwiki_receipt_summary


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


def _source_full_tasks(*, include_wikiwiki: bool) -> list[SourceTask]:
    tasks = [
        SourceTask(
            "akashi-list",
            [
                "{python}",
                "script/project/python_runner.py",
                "script/project/akashi_command.py",
                "full",
                "--skip-start2",
            ],
            "run-akashi-source",
        ),
    ]
    if include_wikiwiki:
        tasks.append(
            SourceTask(
                "wikiwiki-jp",
                [
                    "{python}",
                    "script/project/python_runner.py",
                    "script/project/cli.py",
                    "wikiwiki",
                    "--full",
                    "--skip-start2",
                ],
                "run-wikiwiki-source",
            )
        )
    return tasks


def run(root: Path, args: list[str], config: dict, loader=None):
    if args:
        return result(
            "失败",
            "run 不接受额外参数",
            [],
            ["未知参数：" + " ".join(args)],
            "执行 ./flow run",
            "无需回滚",
            2,
        )
    report_path = root / "dist/data-pipeline/local-validation.json"
    before_log = run_logged(
        root,
        ["{python}", "script/project/python_runner.py", "script/project/check.py", "before"],
        "run-before-check",
    )
    start2_log = run_logged(
        root,
        ["{python}", "script/project/python_runner.py", "script/project/start2_command.py", "ensure"],
        "run-start2",
    )
    wikiwiki_before = wikiwiki_receipt_summary(root)
    source_results = run_source_tasks(root, _source_full_tasks(include_wikiwiki=not bool(wikiwiki_before["ready"])))
    source_lines = [
        f"{source_result.name} source acquisition：{source_result.log_path.relative_to(root)}"
        for source_result in source_results
    ]
    if wikiwiki_before["ready"]:
        source_lines.append("wikiwiki-jp source acquisition：复用 ready receipt（" + str(wikiwiki_before["displayPath"]) + "）")
        source_lines.extend("wikiwiki-jp receipt：" + str(item) for item in wikiwiki_before["details"])
    else:
        wikiwiki_after = wikiwiki_receipt_summary(root)
        source_lines.append("wikiwiki-jp receipt：" + str(wikiwiki_after["line"]))
        source_lines.extend("wikiwiki-jp receipt：" + str(item) for item in wikiwiki_after["details"])
    command = [
        "{python}", "script/project/python_runner.py",
        "script/project/data_pipeline.py",
        "--report", str(report_path.relative_to(root)),
    ]
    log = run_logged(root, command, "data-validate")
    completed = [
        f"before check：{before_log.relative_to(root)}",
        f"Start2/API baseline：{start2_log.relative_to(root)}",
        *source_lines,
        f"本地数据处理日志：{log.relative_to(root)}",
        f"数据报告：{report_path.relative_to(root)}",
        *_reliability_completed_lines(report_path),
    ]
    return result(
        "成功",
        "严格 Spider 数据流程通过（source receipt 已感知，随后本地处理）",
        completed,
        [],
        "检查数据差异后执行 ./flow push",
        "Git 可恢复生成数据",
    )
