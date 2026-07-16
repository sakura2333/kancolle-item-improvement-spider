from __future__ import annotations

"""Thin Spider adapter for ``flow.public``.

The adapter only declares public interfaces and maps project-facing commands
to the native project tool.  Quality composition, Git policy, Spider logic,
npm packaging and Stable projection remain in ``script.project`` or the
product runtime.
"""

from pathlib import Path

from script.project.ownership import recovery_policy, update_policy

HUMAN_COMMANDS = [
    "status", "check", "smoke", "run", "wikiwiki", "push", "beta", "stable", "package", "update", "rollback"
]

_PROJECT_HANDLER = "script.project.cli:flow_handler"

COMMANDS = {
    "status": {"kind": "project", "handler": _PROJECT_HANDLER, "fixedArgs": ["status"], "description": "查看项目状态与下一步"},
    "check": {"kind": "project", "handler": _PROJECT_HANDLER, "fixedArgs": ["check"], "description": "执行项目检查 Profile"},
    "run": {"kind": "project", "handler": _PROJECT_HANDLER, "fixedArgs": ["run"], "description": "运行 Spider 默认目标"},
    "smoke": {"kind": "project", "handler": _PROJECT_HANDLER, "fixedArgs": ["smoke"], "description": "运行小样本完整链路 smoke"},
    "wikiwiki": {"kind": "project", "handler": _PROJECT_HANDLER, "fixedArgs": ["wikiwiki"], "description": "手动刷新 WikiWiki 装备详情浏览器会话来源"},
    "push": {"kind": "project", "handler": _PROJECT_HANDLER, "fixedArgs": ["push"], "description": "提交并推送项目代码"},
    "beta": {"kind": "unsupported", "description": "Beta 当前未启用"},
    "stable": {"kind": "project", "handler": _PROJECT_HANDLER, "fixedArgs": ["stable"], "description": "发布已冻结 Stable 候选"},
    "doctor": {"kind": "project", "handler": _PROJECT_HANDLER, "fixedArgs": ["doctor"], "description": "检查项目环境"},
}

PUBLIC_CAPABILITIES = {
    "status": {"supported": True, "reason": None, "sideEffect": "L0", "profiles": [], "targets": []},
    "check": {"supported": True, "reason": None, "sideEffect": "L1", "profiles": ["quick", "full"], "targets": []},
    "run": {"supported": True, "reason": None, "sideEffect": "L2", "profiles": [], "targets": ["default"]},
    "smoke": {"supported": True, "reason": None, "sideEffect": "L2", "profiles": [], "targets": []},
    "wikiwiki": {"supported": True, "reason": None, "sideEffect": "L2", "profiles": [], "targets": []},
    "push": {"supported": True, "reason": None, "sideEffect": "L3", "profiles": [], "targets": ["default"]},
    "beta": {"supported": False, "reason": "Spider 当前没有独立 Beta 发布面", "sideEffect": "L3", "profiles": [], "targets": []},
    "stable": {"supported": True, "reason": None, "sideEffect": "L4", "profiles": [], "targets": ["public-main"]},
    "package": {"supported": True, "reason": None, "sideEffect": "L1", "profiles": [], "targets": []},
    "update": {"supported": True, "reason": None, "sideEffect": "L2", "profiles": [], "targets": []},
    "rollback": {"supported": True, "reason": None, "sideEffect": "L2", "profiles": [], "targets": []},
    "help": {"supported": True, "reason": None, "sideEffect": "L0", "profiles": [], "targets": []},
    "version": {"supported": True, "reason": None, "sideEffect": "L0", "profiles": [], "targets": []},
    "capabilities": {"supported": True, "reason": None, "sideEffect": "L0", "profiles": [], "targets": []},
    "doctor": {"supported": True, "reason": None, "sideEffect": "L0", "profiles": [], "targets": []},
}


def runtime(root: Path, binding: dict) -> dict:
    source = binding["versionSource"]
    if source.get("type") != "file":
        raise RuntimeError("Spider 当前只支持 file 版本来源")
    return {
        "project": {"id": binding["projectId"], "versionFile": source["value"]},
        "binding": binding,
        "capabilities": {"flow.command": True, "update.transaction": True, "recovery.package": True},
        "humanCommands": HUMAN_COMMANDS,
        "commands": COMMANDS,
        "update": update_policy(root),
        "recovery": recovery_policy(),
        "publicCapabilities": PUBLIC_CAPABILITIES,
    }
