from __future__ import annotations

"""Small-data full-chain smoke for the Spider Flow.

Smoke is a complete-flow probe with small acquisition limits.  It is not a
release/full-source proof: source receipts may remain not-ready after probes,
but the command validates ordering and integration:
Before check -> Start2/API baseline -> parallel source probes -> receipt/log join.
"""

from pathlib import Path

from .command_support import result, run_logged
from .source_phase import SourceTask, run_source_tasks

SMOKE_LIMIT = 3


def _source_probe_tasks(limit: int) -> list[SourceTask]:
    return [
        SourceTask(
            "akashi-list",
            [
                "{python}",
                "script/project/python_runner.py",
                "script/project/akashi_command.py",
                "probe",
                "--daily-limit",
                str(limit),
                "--skip-start2",
            ],
            "smoke-akashi-probe",
        ),
        SourceTask(
            "wikiwiki-jp",
            [
                "{python}",
                "script/project/python_runner.py",
                "script/project/cli.py",
                "wikiwiki",
                "probe",
                "--daily-limit",
                str(limit),
                "--skip-start2",
            ],
            "smoke-wikiwiki-probe",
        ),
    ]


def run(root: Path, args: list[str], config: dict, loader=None) -> dict:
    if args:
        return result(
            "失败",
            "smoke 不接受额外参数",
            [],
            ["未知参数：" + " ".join(args)],
            "执行 ./flow smoke",
            "无需回滚",
            2,
        )

    completed: list[str] = []
    before_log = run_logged(
        root,
        ["{python}", "script/project/python_runner.py", "script/project/check.py", "before"],
        "smoke-before-check",
    )
    completed.append(f"before check：{before_log.relative_to(root)}")

    start2_log = run_logged(
        root,
        ["{python}", "script/project/python_runner.py", "script/project/start2_command.py", "ensure"],
        "smoke-start2",
    )
    completed.append(f"Start2/API baseline：{start2_log.relative_to(root)}")

    source_results = run_source_tasks(root, _source_probe_tasks(SMOKE_LIMIT))
    for source_result in source_results:
        completed.append(f"{source_result.name} source probe：{source_result.log_path.relative_to(root)}")
    completed.extend([
        "Akashi receipt：.flow/local/source-receipts/akashi-list.json（probe 可为 not-ready）",
        "WikiWiki receipt：.flow/local/wikiwiki-crawler/source-receipt.json（probe 可为 not-ready）",
    ])

    return result(
        "成功",
        f"完整流程 smoke 已通过（Start2 + Akashi/WikiWiki 并发 source probe，各 {SMOKE_LIMIT} 条）",
        completed,
        [
            "smoke 是小样本链路验证；source receipts 可能保持 not-ready，不代表 full source ready，也不替代 ./flow run",
            "source acquisition 阶段只下载/写 receipt；本地数据处理必须等 full source ready 后由 ./flow run 执行",
        ],
        "继续执行 ./flow wikiwiki --full 或 ./flow run；run 会先完成 source acquisition，再进入本地处理",
        "无需回滚；source cache/receipt/logs 保留在 .flow/local 与 .flow/state/logs",
    )
