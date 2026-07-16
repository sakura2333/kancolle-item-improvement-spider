from __future__ import annotations

import importlib
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from script import flow_adapter
from .contract import assert_supported_contract, package_identity
from .result import from_project, make, print_result

PUBLIC_COMMANDS = (
    "status", "check", "smoke", "run", "wikiwiki", "run-wikiwiki-source", "push", "beta", "stable", "package", "update-package", "update", "rollback",
    "help", "version", "capabilities", "doctor",
)


def _capability_module(name: str):
    if name not in {"update", "recovery"}:
        raise RuntimeError(f"未知基础能力模块：{name}")
    return importlib.import_module(f"script.flow.{name}")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON 根节点必须是对象：{path}")
    return value


def _binding(root: Path) -> dict[str, Any]:
    path = root / ".flow/project.json"
    if not path.is_file():
        raise RuntimeError("缺少 .flow/project.json；项目尚未接入 Flow Public Contract")
    value = _load_json(path)
    required = {"projectId", "contract", "versionSource", "maintenanceProfile", "publicReleasePolicy"}
    missing = sorted(required - set(value))
    if missing:
        raise RuntimeError(f".flow/project.json 缺少字段：{missing}")
    contract = value.get("contract") or {}
    assert_supported_contract(contract)
    return value


def _load_handler(value: str):
    module_name, function_name = value.split(":", 1)
    return getattr(importlib.import_module(module_name), function_name)


def _parse(argv: list[str]) -> tuple[str, dict[str, Any], list[str]]:
    if not argv or argv[0].startswith("-"):
        command = "status"
        rest = argv
    else:
        command = argv[0]
        rest = argv[1:]
    options: dict[str, Any] = {
        "json": False,
        "nonInteractive": False,
        "confirm": False,
        "profile": None,
        "target": None,
        "output": None,
        "package": None,
        "debug": False,
    }
    project_args: list[str] = []
    index = 0
    while index < len(rest):
        item = rest[index]
        if item == "--json":
            options["json"] = True
        elif item == "--non-interactive":
            options["nonInteractive"] = True
        elif item == "--confirm":
            options["confirm"] = True
        elif item == "--debug":
            options["debug"] = True
        elif item in {"--profile", "--target", "--output", "--package"}:
            if index + 1 >= len(rest):
                raise ValueError(f"{item} 缺少参数")
            options[item[2:].replace("-", "")] = rest[index + 1]
            index += 1
        else:
            project_args.append(item)
        index += 1
    if options["json"]:
        options["nonInteractive"] = True
    return command, options, project_args


def _capabilities(binding: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "projectId": binding["projectId"],
        "contract": {"id": "flow.public", "version": binding["contract"]["version"]},
        "capabilities": dict(runtime["capabilities"]),
        "flowPackage": package_identity(),
        "commands": runtime["publicCapabilities"],
    }


def _help_message(runtime: dict[str, Any]) -> str:
    lines = ["公共命令："]
    for name in runtime["humanCommands"]:
        if name in runtime["commands"]:
            description = runtime["commands"][name]["description"]
        elif name == "package":
            description = "生成 Recovery Package"
        elif name == "update-package":
            description = "生成 Flow contentHash 业务更新包"
        elif name == "update":
            description = "应用当前项目更新"
        elif name == "rollback":
            description = "回滚最近一次更新"
        else:
            description = ""
        lines.append(f"  ./flow {name:<10} {description}")
    lines.extend([
        "",
        "诊断命令：",
        "  ./flow help",
        "  ./flow version",
        "  ./flow capabilities --json",
        "  ./flow doctor",
        "",
        "项目内部构建、npm、数据诊断命令位于 script/project 或 package.json，不进入 Flow 命令空间。",
    ])
    return "\n".join(lines)


def _unsupported(binding: dict[str, Any], command: str, reason: str) -> dict[str, Any]:
    return make(
        binding["projectId"], command, "unsupported", reason,
        first_error=reason, next_action="./flow capabilities --json",
        incomplete=[reason], recovery="无需回滚",
    )


def _validate_public_options(command: str, options: dict[str, Any], capabilities: dict[str, Any]) -> dict[str, Any]:
    item = capabilities["commands"][command]
    if options["profile"] is not None and options["profile"] not in item["profiles"]:
        raise ValueError(f"不支持的 Profile：{options['profile']}")
    if options["target"] is not None and options["target"] not in item["targets"]:
        raise ValueError(f"不支持的 Target：{options['target']}")
    if command != "check" and options["profile"] is not None:
        raise ValueError("--profile 只适用于 check")
    if command not in {"run", "push", "beta", "stable", "run-wikiwiki-source"} and options["target"] is not None:
        raise ValueError("--target 不适用于该命令")
    if command not in {"package", "update-package"} and options["output"] is not None:
        raise ValueError("--output 只适用于 package/update-package")
    if command != "update" and options["package"] is not None:
        raise ValueError("--package 只适用于 update")
    return item


def _execute_project(
    root: Path,
    runtime: dict[str, Any],
    command: str,
    project_args: list[str],
    options: dict[str, Any],
) -> dict[str, Any]:
    item = runtime["commands"][command]
    args = list(item.get("fixedArgs", [])) + list(project_args)
    if command == "check":
        args += ["--profile", options["profile"] or "quick"]
    if options["target"]:
        args += ["--target", options["target"]]
    if options["confirm"]:
        args.append("--confirm")
    return _load_handler(item["handler"])(root, args, runtime, None)


def main(root: Path, argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        command, options, project_args = _parse(argv)
        if command in {"list", "--help", "-h"}:
            command = "help"
        binding = _binding(root)
        runtime = flow_adapter.runtime(root, binding)
        project_id = binding["projectId"]
        capabilities = _capabilities(binding, runtime)
        if command not in PUBLIC_COMMANDS:
            result = make(
                project_id, "help", "invalid-arguments", f"未知命令：{command}",
                first_error=f"未知命令：{command}", next_action="./flow help", recovery="无需回滚",
            )
            print_result(result, as_json=options["json"])
            return int(result["exitCode"])

        command_cap = _validate_public_options(command, options, capabilities)
        if not command_cap["supported"]:
            result = _unsupported(binding, command, str(command_cap["reason"]))
        elif command == "capabilities":
            if options["json"]:
                print(json.dumps(capabilities, ensure_ascii=False, indent=2))
                return 0
            result = make(
                project_id, command, "success", "公共能力声明可用",
                next_action="./flow status", data={"capabilities": capabilities},
                completed=["flow.command：启用", "update.transaction：启用", "recovery.package：启用"],
                recovery="无需回滚",
            )
        elif command == "help":
            result = make(project_id, command, "success", _help_message(runtime), next_action="./flow status", recovery="无需回滚")
        elif command == "version":
            version = (root / runtime["project"]["versionFile"]).read_text("utf-8").strip()
            result = make(project_id, command, "success", version, next_action="./flow status", data={"version": version}, recovery="无需回滚")
        elif command == "package":
            args: list[str] = []
            if options["output"]:
                args += ["--output", options["output"]]
            result = from_project(project_id, command, _capability_module("recovery").execute(root, "create", args, runtime))
        elif command == "update-package":
            args = []
            if options["output"]:
                args += ["--output", options["output"]]
            result = from_project(project_id, command, _execute_project(root, runtime, command, args, options))
        elif command == "update":
            args = []
            if options["package"]:
                args += ["--package", options["package"]]
            if options["confirm"]:
                args.append("--yes")
            if options["nonInteractive"]:
                args.append("--non-interactive")
            result = from_project(project_id, command, _capability_module("update").execute(root, "apply", args, runtime))
        elif command == "rollback":
            args = []
            if options["confirm"]:
                args.append("--yes")
            if options["nonInteractive"]:
                args.append("--non-interactive")
            result = from_project(project_id, command, _capability_module("update").execute(root, "rollback", args, runtime))
        elif command in {"push", "stable"} and options["nonInteractive"] and not options["confirm"]:
            result = make(
                project_id, command, "confirmation-required", "远端写入前需要明确确认",
                next_action=f"./flow {command} --confirm", incomplete=["命令尚未执行"], recovery="无需回滚",
            )
        else:
            result = from_project(project_id, command, _execute_project(root, runtime, command, project_args, options))
        print_result(result, as_json=options["json"])
        return int(result["exitCode"])
    except KeyboardInterrupt:
        try:
            binding = _binding(root)
            current = command if "command" in locals() and command in PUBLIC_COMMANDS else "status"
            result = make(
                binding["projectId"], current, "interrupted", "用户中断命令",
                first_error="用户中断命令", next_action=f"重新执行 ./flow {current}",
                recovery="按 ./flow status 判断是否需要 rollback",
            )
            print_result(result, as_json=bool(locals().get("options", {}).get("json")))
            return 130
        except Exception:
            return 130
    except ValueError as exc:
        binding = _binding(root)
        current = command if "command" in locals() and command in PUBLIC_COMMANDS else "help"
        result = make(
            binding["projectId"], current, "invalid-arguments", str(exc),
            first_error=str(exc), next_action=f"./flow {current} --help", recovery="无需回滚",
        )
        print_result(result, as_json=bool(locals().get("options", {}).get("json")))
        return 2
    except Exception as exc:
        if locals().get("options", {}).get("debug"):
            traceback.print_exc()
        try:
            binding = _binding(root)
            current = command if "command" in locals() and command in PUBLIC_COMMANDS else "status"
            kind = "verification-failed" if current == "check" else "execution-failed"
            if current in {"update", "rollback"}:
                kind = "transaction-failed-restored"
            result = make(
                binding["projectId"], current, kind, str(exc), first_error=str(exc),
                next_action="修复首个错误后重新执行原命令",
                recovery="执行 ./flow status；存在回滚点时执行 ./flow rollback",
            )
            print_result(result, as_json=bool(locals().get("options", {}).get("json")))
            return int(result["exitCode"])
        except Exception:
            print(f"Flow 启动失败：{exc}", file=sys.stderr)
            return 1
