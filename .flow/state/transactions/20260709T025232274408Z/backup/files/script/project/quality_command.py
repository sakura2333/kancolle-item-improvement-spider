from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from script.project.environment import inspect_project_environment
from .command_support import git, result, run_logged


def run(root: Path, args: list[str], config: dict, loader):
    environment = inspect_project_environment(root)
    if not environment["ready"]:
        message = str(environment["error"])
        return result(
            "失败",
            message,
            [],
            [message],
            str(environment["nextAction"]),
            "无需回滚；环境初始化不会修改项目源码",
            exit_code=20,
        )

    profile_aliases = {"quick": "before"}
    requested = []
    for profile in ("before", "after", "quick", "full", "release"):
        if f"--{profile}" in args or profile in args:
            requested.append(profile_aliases.get(profile, profile))
    requested = list(dict.fromkeys(requested))
    if len(requested) > 1:
        raise ValueError(f"检查阶段/Profile 冲突：{requested}")
    profile = requested[0] if requested else "before"
    if profile not in config["quality"]:
        raise ValueError(f"未配置检查 Profile：{profile}")
    logs = []
    for index, command in enumerate(config["quality"][profile], 1):
        logs.append(run_logged(root, command, f"quality-{profile}-{index}").relative_to(root).as_posix())
    state = root / ".flow/state/checks"
    state.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "profile": profile,
        "commit": git(root, "rev-parse", "HEAD", check=False),
        "tree": git(root, "rev-parse", "HEAD^{tree}", check=False),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "python": environment["python"],
        "dependencies": environment["dependencies"],
        "logs": logs,
    }
    (state / f"{profile}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result(
        "成功",
        f"{profile} 检查通过",
        [f"执行 {len(logs)} 个检查阶段", "项目 Python 环境与固定依赖版本一致"],
        [],
        "./flow run 或 ./flow push",
        "无需回滚",
    )
