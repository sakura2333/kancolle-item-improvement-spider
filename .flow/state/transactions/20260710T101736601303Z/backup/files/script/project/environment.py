from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

MINIMUM_PYTHON = (3, 11)
REQUIRED_DISTRIBUTIONS = {
    "lxml": "6.0.2",
    "mojimoji": "0.0.13",
    "requests": "2.32.5",
}


def venv_python(root: Path) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _common_repository_root(root: Path) -> Path | None:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode or not completed.stdout.strip():
        return None
    common_dir = Path(completed.stdout.strip()).resolve()
    return common_dir.parent if common_dir.name == ".git" else None


def _environment_root(root: Path) -> Path:
    if os.getenv("FLOW_STAGING") != "1":
        return root
    return _common_repository_root(root) or root


def inspect_python(python: Path) -> dict[str, Any]:
    if not python.is_file() or not os.access(python, os.X_OK):
        return {
            "ready": False,
            "python": str(python),
            "error": "项目 Python 虚拟环境尚未初始化",
            "nextAction": "python3 script/project/init_env.py",
        }
    probe = (
        "import importlib.metadata as m, json, sys; "
        "expected=" + repr(REQUIRED_DISTRIBUTIONS) + "; "
        "actual={name:m.version(name) for name in expected}; "
        "print(json.dumps({'version':[sys.version_info.major,sys.version_info.minor],"
        "'actual':actual,'expected':expected}))"
    )
    completed = subprocess.run(
        [str(python), "-c", probe],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "依赖探测失败").strip().splitlines()[-1]
        return {
            "ready": False,
            "python": str(python),
            "error": f"项目 Python 依赖不完整：{detail}",
            "nextAction": "python3 script/project/init_env.py --recreate",
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "ready": False,
            "python": str(python),
            "error": "项目 Python 环境探测输出无效",
            "nextAction": "python3 script/project/init_env.py --recreate",
        }
    version = tuple(payload.get("version") or ())
    if version < MINIMUM_PYTHON:
        return {
            "ready": False,
            "python": str(python),
            "error": f"项目 Python 版本过低：{'.'.join(map(str, version))}",
            "nextAction": "使用 Python 3.11+ 执行 python3 script/project/init_env.py --recreate",
        }
    actual = payload.get("actual") or {}
    expected = payload.get("expected") or REQUIRED_DISTRIBUTIONS
    mismatch = [
        f"{name}={actual.get(name)!r}（需要 {required}）"
        for name, required in expected.items()
        if actual.get(name) != required
    ]
    if mismatch:
        return {
            "ready": False,
            "python": str(python),
            "error": "项目 Python 依赖版本不一致：" + ", ".join(mismatch),
            "nextAction": "python3 script/project/init_env.py --recreate",
        }
    return {
        "ready": True,
        "python": str(python),
        "version": list(version),
        "dependencies": actual,
        "error": None,
        "nextAction": "./flow check --profile full",
    }


def inspect_project_environment(root: Path) -> dict[str, Any]:
    return inspect_python(venv_python(_environment_root(root)))
