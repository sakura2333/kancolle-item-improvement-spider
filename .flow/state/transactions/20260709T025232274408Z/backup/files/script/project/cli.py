#!/usr/bin/env python3
from __future__ import annotations

"""Native Spider engineering tool.

This is not a second public Flow interface.  Flow delegates project targets to
this module; CI and maintainers may also call it directly when they need the
underlying project operation.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from script.project import candidate_verify, push_command, quality_command, run_command, smoke_command, stable_command, status_command, wikiwiki_command
from script.project.command_support import result
from script.project.environment import inspect_project_environment
from script.project.ownership import project_owned_identity
from script.project.runtime import load as load_runtime



def _doctor(root: Path, args: list[str], config: dict, loader=None) -> dict:
    environment = inspect_project_environment(root)
    completed = ["项目工具层可加载", "generated-state 与 project-owned 边界可读取"]
    incomplete: list[str] = []
    if environment["ready"]:
        completed.append("项目 Python 环境与固定依赖版本一致")
    else:
        incomplete.append(str(environment["error"]))
    try:
        identity = project_owned_identity(root)
        completed.append(f"代码内容身份：{identity[:12]}")
    except Exception as exc:  # pragma: no cover - surfaced as diagnostic data
        incomplete.append(f"代码内容身份不可计算：{exc}")
    return result(
        "成功",
        "项目工程工具检查完成" if not incomplete else "项目工程工具可启动，但存在待处理项",
        completed,
        incomplete,
        str(environment["nextAction"]) if not environment["ready"] else "./flow check --profile quick",
        "无需回滚",
    )


def _normalize_check_args(args: list[str]) -> list[str]:
    values = list(args)
    if "--profile" in values:
        index = values.index("--profile")
        if index + 1 >= len(values):
            raise ValueError("--profile 缺少值")
        profile = values[index + 1]
        del values[index : index + 2]
        if profile not in {"before", "after", "quick", "full"}:
            raise ValueError(f"不支持的检查 Profile：{profile}")
        values.insert(0, f"--{profile}")
    for alias in ("before", "after"):
        if alias in values:
            values[values.index(alias)] = f"--{alias}"
    return values


def flow_handler(root: Path, args: list[str], adapter_config: dict | None = None, loader=None) -> dict:
    if not args:
        raise ValueError("项目工具缺少命令")
    command, rest = args[0], list(args[1:])
    config = load_runtime()
    handlers = {
        "status": status_command.run,
        "check": quality_command.run,
        "run": run_command.run,
        "smoke": smoke_command.run,
        "wikiwiki": wikiwiki_command.run,
        "push": push_command.run,
        "stable": stable_command.run,
        "doctor": _doctor,
        "verify-candidate": candidate_verify.run,
    }
    if command not in handlers:
        raise ValueError(f"未知项目工具命令：{command}")
    if command == "check":
        rest = _normalize_check_args(rest)
    return handlers[command](root, rest, config, loader)


def _print_human(value: dict) -> None:
    print(value.get("current") or value.get("status") or "完成")
    for item in value.get("completed") or []:
        print(f"[完成] {item}")
    for item in value.get("incomplete") or []:
        print(f"[待处理] {item}")
    if value.get("next"):
        print(f"下一步：{value['next']}")


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in values
    values = [item for item in values if item != "--json"]
    try:
        if values and values[0] == "identity":
            payload = {
                "schemaVersion": 1,
                "scheme": "project-owned-sha256",
                "value": project_owned_identity(PROJECT_ROOT),
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2) if as_json else payload["value"])
            return 0
        value = flow_handler(PROJECT_ROOT, values)
    except Exception as exc:
        value = result("失败", str(exc), [], [str(exc)], "修复首个错误后重试", "无需回滚", 1)
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        _print_human(value)
    return int(value.get("exitCode", 0))


if __name__ == "__main__":
    raise SystemExit(main())
