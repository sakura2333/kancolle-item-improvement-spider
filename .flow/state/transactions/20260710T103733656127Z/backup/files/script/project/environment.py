from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

REQUIRED_PYTHON = (3, 14)
REQUIRED_UV = "0.11.28"
REQUIRED_DISTRIBUTIONS = {
    "jaconv": "0.5.0",
    "lxml": "6.0.2",
    "playwright": "1.61.0",
    "requests": "2.32.5",
}
PROJECT_FILES = ("mise.toml", "pyproject.toml", "uv.lock")
NEXT_ACTION = "mise install && mise exec -- uv sync --locked"


def _failure(root: Path, error: str) -> dict[str, Any]:
    return {
        "ready": False,
        "project": str(root),
        "error": error,
        "nextAction": NEXT_ACTION,
    }


def _mise_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["MISE_TRUSTED_CONFIG_PATHS"] = str(root)
    return env


def _run_mise(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    mise = shutil.which("mise")
    if not mise:
        raise FileNotFoundError("mise")
    return subprocess.run(
        [mise, "exec", "--", *args],
        cwd=root,
        env=_mise_env(root),
        text=True,
        capture_output=True,
        check=False,
    )


def inspect_project_environment(root: Path) -> dict[str, Any]:
    root = root.resolve()
    mise = shutil.which("mise")
    if not mise:
        return _failure(root, "未找到 mise；请先安装并启用 mise")
    missing = [name for name in PROJECT_FILES if not (root / name).is_file()]
    if missing:
        return _failure(root, "项目 mise/uv 契约缺失：" + ", ".join(missing))

    tools = _run_mise(root, "python", "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    if tools.returncode:
        detail = (tools.stderr or tools.stdout or "mise Python 探测失败").strip().splitlines()[-1]
        return _failure(root, f"mise Python 3.14 环境不可用：{detail}")
    version_text = tools.stdout.strip().splitlines()[-1] if tools.stdout.strip() else ""
    if version_text != "3.14":
        return _failure(root, f"mise Python 版本不一致：{version_text or 'unknown'}（需要 3.14）")

    uv_version_result = _run_mise(root, "uv", "--version")
    if uv_version_result.returncode:
        detail = (uv_version_result.stderr or uv_version_result.stdout or "mise uv 探测失败").strip().splitlines()[-1]
        return _failure(root, f"mise 管理的 uv 不可用：{detail}")
    uv_version = uv_version_result.stdout.strip().split()[-1]
    if uv_version != REQUIRED_UV:
        return _failure(root, f"mise uv 版本不一致：{uv_version or 'unknown'}（需要 {REQUIRED_UV}）")

    lock_check = _run_mise(root, "uv", "lock", "--check", "--project", str(root))
    if lock_check.returncode:
        detail = (lock_check.stderr or lock_check.stdout or "uv.lock 校验失败").strip().splitlines()[-1]
        return _failure(root, f"项目 uv.lock 与 pyproject.toml 不一致：{detail}")

    probe = (
        "import importlib.metadata as m, json, sys; "
        "expected=" + repr(REQUIRED_DISTRIBUTIONS) + "; "
        "actual={name:m.version(name) for name in expected}; "
        "print(json.dumps({'version':[sys.version_info.major,sys.version_info.minor],"
        "'actual':actual,'expected':expected}))"
    )
    completed = _run_mise(root, "uv", "run", "--locked", "--project", str(root), "python", "-c", probe)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "uv 环境探测失败").strip().splitlines()[-1]
        return _failure(root, f"项目 uv 环境不可用：{detail}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return _failure(root, "项目 uv 环境探测输出无效")

    version = tuple(payload.get("version") or ())
    if version != REQUIRED_PYTHON:
        return _failure(root, f"项目 Python 版本不一致：{'.'.join(map(str, version)) or 'unknown'}（需要 3.14）")
    actual = payload.get("actual") or {}
    expected = payload.get("expected") or REQUIRED_DISTRIBUTIONS
    mismatch = [
        f"{name}={actual.get(name)!r}（需要 {required}）"
        for name, required in expected.items()
        if actual.get(name) != required
    ]
    if mismatch:
        return _failure(root, "项目 Python 依赖版本不一致：" + ", ".join(mismatch))
    return {
        "ready": True,
        "project": str(root),
        "mise": mise,
        "uv": uv_version,
        "version": list(version),
        "dependencies": actual,
        "error": None,
        "nextAction": "./flow check --profile full",
    }
