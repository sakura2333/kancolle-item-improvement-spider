from __future__ import annotations

"""Small-data full-chain smoke for the Spider Flow.

Smoke is a complete-flow probe with small acquisition limits.  It is not a
release/full-source proof: WikiWiki source receipt may remain not-ready after
three detail pages, but the command validates ordering and integration:
Before check -> Start2/API baseline -> WikiWiki three-index catalog -> three
WikiWiki equipment details -> receipt/log diagnostics.
"""

from pathlib import Path

from .command_support import result, run_logged

SMOKE_LIMIT = 3


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

    wikiwiki_log = run_logged(
        root,
        [
            "{python}",
            "script/project/python_runner.py",
            "script/project/cli.py",
            "wikiwiki",
            "probe",
            "--daily-limit",
            str(SMOKE_LIMIT),
            "--skip-start2",
        ],
        "smoke-wikiwiki-probe",
    )
    completed.append(f"WikiWiki 三索引 + {SMOKE_LIMIT} 条详情 probe：{wikiwiki_log.relative_to(root)}")
    completed.append("source receipt：.flow/local/wikiwiki-crawler/source-receipt.json（probe 可为 not-ready）")

    return result(
        "成功",
        f"完整流程 smoke 已通过（Start2 + WikiWiki 三索引 + {SMOKE_LIMIT} 条详情）",
        completed,
        ["smoke 是小样本链路验证；source receipt 可能保持 not-ready，不代表 WikiWiki full source ready，也不替代 ./flow run"],
        "继续执行 ./flow wikiwiki --full；source receipt ready 后再执行 ./flow run",
        "无需回滚；source cache/receipt/logs 保留在 .flow/local 与 .flow/state/logs",
    )
