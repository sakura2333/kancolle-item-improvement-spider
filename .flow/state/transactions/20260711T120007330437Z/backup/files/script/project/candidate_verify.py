#!/usr/bin/env python3
from __future__ import annotations

"""Deterministic candidate verification for Flow update staging.

This belongs to the project engineering-tool layer.  Flow invokes it as one
opaque verifier and only consumes its exit code/result; Flow does not know the
individual checks below.
"""

import os
import subprocess
import sys
from pathlib import Path

from .command_support import result

FLOW_TEST_MODULES = (
    "tests.test_flow_command",
    "tests.test_flow_baseline",
    "tests.test_gpt_update_workflow.FlowContentUpdateTransactionTest",
    "tests.test_project_ownership",
    "tests.test_script_convergence",
)


def _run(root: Path, command: list[str]) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    completed = subprocess.run(
        command,
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode:
        detail = (completed.stdout or "候选检查失败").strip()
        raise RuntimeError(detail)


def run(root: Path, args: list[str], config: dict, loader=None) -> dict:
    _run(root, [sys.executable, "script/project/check.py", "--code-candidate"])
    _run(root, [sys.executable, "-m", "unittest", "-v", *FLOW_TEST_MODULES])
    return result(
        "成功",
        "候选代码的离线控制面检查通过",
        [
            "项目静态检查通过",
            f"控制面回归模块：{len(FLOW_TEST_MODULES)}",
            "未执行网络抓取、Git push 或 npm publish",
        ],
        [],
        "由可信更新事务继续完成身份对账与切换",
        "候选尚未切换，无需回滚",
    )
