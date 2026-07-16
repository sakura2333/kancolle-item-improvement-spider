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



def _wikiwiki_reference_diagnostic_lines(root: Path, *, limit: int = 8) -> list[str]:
    path = root / "dist/data-pipeline/sources/wikiwiki-equipment-detail/reference-diagnostics.json"
    if not path.is_file():
        return [
            "WikiWiki 解析诊断：未生成 reference-diagnostics.json（请查看 data-validate 日志）"
        ]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"WikiWiki 解析诊断：读取失败 {exc}"]
    resolved = int(payload.get("resolvedLinkTargetConflictCount") or 0)
    unresolved = int(payload.get("operatorStopReferenceCount") or 0)
    lines = [
        "WikiWiki 解析诊断："
        f"已收敛 linkTarget 冲突={resolved}，"
        f"未收敛引用问题={unresolved}，"
        "报告=dist/data-pipeline/sources/wikiwiki-equipment-detail/reference-diagnostics.md"
    ]
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    interesting = rows[: max(limit, 0)]
    for row in interesting:
        if not isinstance(row, dict):
            continue
        accepted = row.get("acceptedShip") if isinstance(row.get("acceptedShip"), dict) else {}
        accepted_text = ""
        if accepted:
            accepted_text = (
                f" accepted={accepted.get('shipId')}:{accepted.get('shipName')}"
            )
        candidates = row.get("candidateShips") if isinstance(row.get("candidateShips"), list) else []
        candidate_text = ",".join(
            f"{candidate.get('shipId')}:{candidate.get('shipName')}"
            for candidate in candidates
            if isinstance(candidate, dict)
        )
        if candidate_text:
            candidate_text = f" candidates={candidate_text}"
        lines.append(
            "WikiWiki 解析诊断项："
            f"{row.get('category')} "
            f"equipment={row.get('equipmentId')}:{row.get('equipmentName')} "
            f"rawName={row.get('rawName')} "
            f"linkTarget={row.get('linkTarget')}"
            f"{accepted_text}{candidate_text} "
            f"reason={row.get('reason') or row.get('kind') or row.get('message')}"
        )
    if len(rows) > len(interesting):
        lines.append(f"WikiWiki 解析诊断项：其余 {len(rows) - len(interesting)} 项见 reference-diagnostics.md")
    return lines


def _improvement_assistant_reverse_lines(root: Path, *, limit: int = 12) -> list[str]:
    path = root / "dist/data-pipeline/sources/improvement-assistant-reverse/assistant-day-reverse-index.json"
    if not path.is_file():
        return [
            "改修秘书舰反查：未生成 assistant-day-reverse-index.json（请查看 data-validate 日志）"
        ]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"改修秘书舰反查：读取失败 {exc}"]
    threshold = int(payload.get("threshold") or 3)
    over_count = int(payload.get("overThresholdShipDayCount") or 0)
    max_count = int(payload.get("maxEquipmentCount") or 0)
    lines = [
        "改修秘书舰反查："
        f"阈值=>{threshold}，"
        f"超过阈值的舰/日={over_count}，"
        f"最大装备数={max_count}，"
        "报告=dist/data-pipeline/sources/improvement-assistant-reverse/assistant-day-reverse-index.md"
    ]
    rows = payload.get("overThreshold") if isinstance(payload.get("overThreshold"), list) else []
    for row in rows[: max(limit, 0)]:
        if not isinstance(row, dict):
            continue
        equipments = row.get("equipments") if isinstance(row.get("equipments"), list) else []
        equipment_text = ",".join(
            f"{item.get('equipmentId')}:{item.get('equipmentName')}"
            for item in equipments[:5]
            if isinstance(item, dict)
        )
        if len(equipments) > 5:
            equipment_text += f",...(+{len(equipments) - 5})"
        lines.append(
            "改修秘书舰反查项："
            f"day={row.get('dayName')}({row.get('dayIndex')}) "
            f"ship={row.get('shipId')}:{row.get('shipName')} "
            f"equipmentCount={row.get('equipmentCount')} "
            f"equipments={equipment_text}"
        )
    if len(rows) > limit:
        lines.append(f"改修秘书舰反查项：其余 {len(rows) - limit} 项见 assistant-day-reverse-index.md")
    return lines

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
        *_wikiwiki_reference_diagnostic_lines(root),
        *_improvement_assistant_reverse_lines(root),
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
