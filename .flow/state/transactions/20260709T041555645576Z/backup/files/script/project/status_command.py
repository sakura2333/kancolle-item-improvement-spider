from __future__ import annotations

from pathlib import Path

import json
from .command_support import git, result
from .ownership import git_dirty_paths, split_paths
from .flow_baseline import assert_state_matches_current, read_state


def run(root: Path, args: list[str], config: dict, loader=None):
    version = (root / config["project"]["versionFile"]).read_text("utf-8").strip()
    branch = git(root, "branch", "--show-current", check=False) or "detached"
    head = git(root, "rev-parse", "--short", "HEAD", check=False) or "unknown"
    dirty = split_paths(root, git_dirty_paths(root))
    code_count = len(dirty["project-owned"])
    generated_count = len(dirty["generated-state"])
    local_count = len(dirty["local-preserved"])
    state = (
        f"{config['project']['id']} {version}，{branch}@{head}，"
        f"代码变更 {code_count}，生成数据变更 {generated_count}，本机状态变更 {local_count}"
    )
    development = config["git"]["development"]
    upstream_ref = f"{development['remote']}/{development['branch']}...{development['branch']}"
    upstream = git(root, "rev-list", "--left-right", "--count", upstream_ref, check=False)
    completed = [
        "Flow 1.1 公共接口绑定可读取",
        "项目工具与生成数据边界已分离",
        f"项目路径：{root.resolve()}",
    ]
    if upstream:
        completed.append(f"{development['remote']}/{development['branch']} 对账：{upstream}")
    incomplete: list[str] = []
    local_path = root / ".flow/local.json"
    if local_path.is_file():
        local = json.loads(local_path.read_text(encoding="utf-8"))
        workspace = Path(str(local["workspaceRoot"])).expanduser().resolve()
        download = Path(str(local["downloadRoot"])).expanduser().resolve()
        project_path = Path(str(local["projectPath"])).expanduser().resolve()
        if project_path == root.resolve():
            completed.append("Project Path 与当前目录一致")
        else:
            incomplete.append(f"Project Path 不一致：{project_path}")
        if root.resolve().is_relative_to(workspace):
            completed.append(f"Workspace Root：{workspace}")
        else:
            incomplete.append(f"项目不位于 Workspace Root：{workspace}")
        if download.is_dir():
            completed.append(f"Download Root：{download}")
        else:
            incomplete.append(f"Download Root 不可访问：{download}")
    else:
        incomplete.append("尚未创建 .flow/local.json")
    baseline = read_state(root)
    if baseline is None:
        incomplete.append("尚未建立 Flow baseline state")
    else:
        try:
            assert_state_matches_current(root, baseline)
            completed.append(f"Flow baseline 对账通过：{str(baseline.get('contentHash', ''))[:19]}")
        except Exception as exc:
            incomplete.append(str(exc))
    if generated_count:
        completed.append(f"生成数据保持独立：{generated_count} 个变化不会进入代码 push/update identity")
    if code_count:
        incomplete.append(f"存在 {code_count} 个 project-owned 代码变化")
    next_step = "./flow check --profile quick" if code_count else "./flow run 或继续开发"
    return result("成功", state, completed, incomplete, next_step, "./flow rollback（仅在存在更新回滚点时）")
