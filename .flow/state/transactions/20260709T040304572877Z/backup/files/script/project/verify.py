#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from _common import (
    PACKAGE_DIR,
    PROJECT_ROOT,
    ProjectCommandError,
    main_guard,
    parse_json_output,
    project_env,
    require_tool,
    run,
)
from _project_checks import run_basic_checks, verify_versions

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service.generated_state.config import (
    GeneratedStateConfigError,
    load_generated_state_config,
)

REQUIRED_PACKAGE_FILES = {
    "index.js",
    "index.d.ts",
    "manifest.json",
    "README.md",
    "CHANGELOG.md",
    "LICENSES.md",
    "RELEASES.json",
    "schemas/improvement-detail.schema.json",
    "improvement/list.json",
    "improvement/detail.nedb",
    "equipment/drop-from.nedb",
    "equipment/special-bonuses.nedb",
    "audit/build-report.json",
}

FORBIDDEN_PACKAGE_PREFIXES = (
    "node_modules/",
    "data/",
    "tests/",
    ".github/",
    "service/",
    "util/",
)


def _verify_versions(*, include_generated_state: bool = True) -> None:
    verify_versions(include_generated_state=include_generated_state)


def _verify_generated_state_contract() -> None:
    try:
        config = load_generated_state_config()
    except (OSError, ValueError, GeneratedStateConfigError) as exc:
        raise ProjectCommandError(f"generated-state 配置无效：{exc}") from exc
    if config.ref != "online":
        raise ProjectCommandError(f"Spider generated-state ref 必须为 online，当前为 {config.ref!r}")
    required_baselines = {
        "dist/data-pipeline/improvement",
        "dist/data-pipeline/start2_data",
        "dist/data-pipeline/assets",
        "dist/data-pipeline/sources",
        "dist/packages/kancolle-data/CHANGELOG.md",
        "dist/packages/kancolle-data/RELEASES.json",
        "dist/packages/kancolle-data/manifest.json",
    }
    missing = sorted(required_baselines - set(config.baseline_sync_paths))
    if missing:
        raise ProjectCommandError(
            "generated-state 回流契约缺少完整开发基线：\n"
            + "\n".join(f"- {item}" for item in missing)
        )

def _verify_automation_contract() -> None:
    binding_path = PROJECT_ROOT / ".flow" / "project.json"
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    expected_top = {"projectId", "contract", "versionSource", "maintenanceProfile", "publicReleasePolicy"}
    if set(binding) != expected_top:
        raise ProjectCommandError(f".flow/project.json 字段发生漂移：{sorted(set(binding) ^ expected_top)}")
    if binding["projectId"] != "kancolle-item-improvement-spider":
        raise ProjectCommandError("Flow 项目身份不一致")
    contract = binding["contract"]
    required_contract = {"id", "version", "repository", "entry", "commit", "tag", "contractSha256"}
    if set(contract) != required_contract:
        raise ProjectCommandError("Flow 公约绑定字段不完整")
    if contract != {
        "id": "flow.public",
        "version": "1.1.0",
        "repository": "http://192.168.1.129:13000/personal/infra-flow-contract-temp",
        "entry": "contracts/flow/FLOW-PUBLIC-CONTRACT.md",
        "commit": "6c0edc923ae24b7f5c01af5044c4a46d5d59806b",
        "tag": "flow-public-v1.1.0",
        "contractSha256": "749f478eca87f512645eb04736061bf9b94235be412553eefdd2581ea4c5eb5e",
    }:
        raise ProjectCommandError("项目 Flow 1.1.0 正式绑定发生漂移")
    if binding["versionSource"] != {"type": "file", "value": "VERSION"}:
        raise ProjectCommandError("Spider 版本唯一事实必须是 VERSION")
    if binding["maintenanceProfile"] != "ai-maintained":
        raise ProjectCommandError("Spider 必须采用 ai-maintained 维护档案")

    from script import flow_adapter
    from script.project.ownership import generated_patterns, project_owned_identity
    from script.project.runtime import load as load_project_runtime

    runtime = flow_adapter.runtime(PROJECT_ROOT, binding)
    if runtime["capabilities"] != {
        "flow.command": True,
        "update.transaction": True,
        "recovery.package": True,
    }:
        raise ProjectCommandError("基础能力必须且只能启用 flow.command/update.transaction/recovery.package")
    expected_human = ["status", "check", "smoke", "run", "wikiwiki", "push", "beta", "stable", "package", "update-package", "update", "rollback"]
    if runtime["humanCommands"] != expected_human:
        raise ProjectCommandError("人类意图命令集合发生漂移")
    expected_public = set(expected_human + ["help", "version", "capabilities", "doctor"])
    if set(runtime["publicCapabilities"]) != expected_public:
        raise ProjectCommandError("公共能力声明不完整")
    if any(":" in name for name in runtime["commands"]):
        raise ProjectCommandError("Flow 适配层重新暴露了旧私有精确命令")
    retired_flow_tasks = PROJECT_ROOT / "script/flow_tasks"
    retired_sources = list(retired_flow_tasks.glob("*.py")) + list(retired_flow_tasks.glob("*.md"))
    if (PROJECT_ROOT / "script/project_flow.py").exists() or retired_sources:
        raise ProjectCommandError("旧项目控制中心源码仍存在")
    if runtime["publicCapabilities"]["push"]["sideEffect"] not in {"L3", "L4"}:
        raise ProjectCommandError("push 副作用等级低报")
    if runtime["publicCapabilities"]["stable"]["sideEffect"] != "L4":
        raise ProjectCommandError("stable 必须是 L4")

    protected = runtime["update"]["protected"]
    for pattern in generated_patterns(PROJECT_ROOT):
        if pattern not in protected:
            raise ProjectCommandError(f"generated-state 未被更新事务隔离：{pattern}")
    if runtime["update"].get("identityProvider") != "script.project.ownership:identity_value":
        raise ProjectCommandError("更新事务没有使用 project-owned 内容身份")
    if not runtime["update"].get("autoCommit") or not runtime["update"].get("autoCommitRollback"):
        raise ProjectCommandError("更新与回滚事务必须自动提交 project-owned 内容")
    if not re.fullmatch(r"[0-9a-f]{64}", project_owned_identity(PROJECT_ROOT)):
        raise ProjectCommandError("project-owned 内容身份不可复算")

    project_runtime = load_project_runtime()
    stable = project_runtime["stable"]
    for required in (".flow/**", "script/**", "tests/**", "docs/internal/**"):
        if required not in stable["internalOnly"]:
            raise ProjectCommandError(f"Stable 内网隔离缺少 {required}")
    if ".github/workflows/data-pipeline.yml" not in stable["include"]:
        raise ProjectCommandError("Stable 必须包含公开产品数据流水线")

    if (PROJECT_ROOT / ".devops").exists():
        raise ProjectCommandError("旧 .devops 控制面仍存在")
    duplicate_fact_sources = list(PROJECT_ROOT.glob("**/flow-runtime.json")) + list(PROJECT_ROOT.glob("**/project-flow.json"))
    if duplicate_fact_sources:
        raise ProjectCommandError(
            "存在重复 Flow 配置事实源："
            + ", ".join(path.relative_to(PROJECT_ROOT).as_posix() for path in duplicate_fact_sources)
        )
    parallel_entries = [
        path for pattern in ("*.command", "*.cmd")
        for path in PROJECT_ROOT.glob(pattern)
        if path.name != "flow.cmd"
    ]
    if parallel_entries:
        raise ProjectCommandError("存在第二个公共入口：" + ", ".join(path.name for path in parallel_entries))

    local_path = PROJECT_ROOT / ".flow" / "local.json"
    if local_path.is_file():
        local = json.loads(local_path.read_text(encoding="utf-8"))
        repository = Path(str(local.get("contractRepositoryPath", ""))).expanduser()
        contract_file = repository / contract["entry"]
        if repository.is_dir() and contract_file.is_file():
            import hashlib
            digest = hashlib.sha256(contract_file.read_bytes()).hexdigest()
            if digest != contract["contractSha256"]:
                raise ProjectCommandError("本地公约正文与绑定 SHA-256 不一致")


def _verify_pack_list() -> None:
    require_tool("npm")
    run(["npm", "run", "check"], cwd=PACKAGE_DIR, env=project_env())
    completed = run(
        ["npm", "pack", "--dry-run", "--json", "--ignore-scripts"],
        cwd=PACKAGE_DIR,
        env=project_env(),
        capture_output=True,
    )
    value = parse_json_output(completed.stdout)
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ProjectCommandError("npm pack --dry-run 返回了非预期结果")
    files = value[0].get("files", [])
    paths = {
        str(item.get("path", "")).lstrip("./")
        for item in files
        if isinstance(item, dict)
    }
    missing = sorted(REQUIRED_PACKAGE_FILES - paths)
    forbidden = sorted(
        path
        for path in paths
        if path.endswith(".tgz") or path.startswith(FORBIDDEN_PACKAGE_PREFIXES)
    )
    if missing:
        raise ProjectCommandError("npm 包缺少必要文件：\n" + "\n".join(f"- {item}" for item in missing))
    if forbidden:
        raise ProjectCommandError("npm 包包含禁止文件：\n" + "\n".join(f"- {item}" for item in forbidden))


def execute() -> None:
    run_basic_checks()
    _verify_generated_state_contract()
    _verify_automation_contract()
    _verify_pack_list()
    print("[完成] 项目离线验证通过")


def main() -> int:
    return main_guard(execute)


if __name__ == "__main__":
    raise SystemExit(main())
