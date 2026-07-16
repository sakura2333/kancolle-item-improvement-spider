#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VENV = PROJECT_ROOT / ".venv"
try:
    from script.project.environment import MINIMUM_PYTHON, REQUIRED_DISTRIBUTIONS
except ModuleNotFoundError:
    from environment import MINIMUM_PYTHON, REQUIRED_DISTRIBUTIONS


class EnvironmentInitError(RuntimeError):
    pass


def _resolve_python(explicit: str | None) -> str:
    candidates = [explicit] if explicit else ["python3.12", "python3.11", "python3.13", "python3.14", "python3"]
    for candidate in candidates:
        if not candidate:
            continue
        path = shutil.which(candidate) if not os.path.isabs(candidate) else candidate
        if not path or not Path(path).is_file():
            continue
        completed = subprocess.run(
            [path, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            continue
        try:
            major, minor = (int(value) for value in completed.stdout.strip().split(".", 1))
        except (TypeError, ValueError):
            continue
        if (major, minor) >= MINIMUM_PYTHON:
            return str(Path(path).resolve())
    requested = explicit or "python3.11+"
    raise EnvironmentInitError(f"找不到可用的 Python 3.11+：{requested}")


def _run(argv: list[str]) -> None:
    print("$", " ".join(argv), flush=True)
    completed = subprocess.run(argv, cwd=PROJECT_ROOT, check=False)
    if completed.returncode != 0:
        raise EnvironmentInitError(
            f"命令失败（{completed.returncode}）：{' '.join(argv)}"
        )


def execute(
    *,
    python: str | None = None,
    venv: Path = DEFAULT_VENV,
    recreate: bool = False,
    skip_pip_upgrade: bool = False,
    wheel_dir: Path | None = None,
    offline: bool = False,
) -> Path:
    interpreter = _resolve_python(python)
    target = venv.expanduser()
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    target = target.resolve()
    if target == PROJECT_ROOT or PROJECT_ROOT not in target.parents:
        raise EnvironmentInitError("虚拟环境必须位于 Spider 项目目录内部")
    if recreate and target.exists():
        shutil.rmtree(target)
    if not target.exists():
        _run([interpreter, "-m", "venv", str(target)])
    venv_python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not venv_python.is_file():
        raise EnvironmentInitError(f"虚拟环境缺少 Python：{venv_python}")
    if offline and wheel_dir is None:
        raise EnvironmentInitError("离线安装必须提供 --wheel-dir")
    resolved_wheel_dir: Path | None = None
    if wheel_dir is not None:
        resolved_wheel_dir = wheel_dir.expanduser().resolve()
        if not resolved_wheel_dir.is_dir():
            raise EnvironmentInitError(f"Wheel 目录不存在：{resolved_wheel_dir}")
    if not skip_pip_upgrade and not offline:
        _run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])
    install = [str(venv_python), "-m", "pip", "install"]
    if resolved_wheel_dir is not None:
        install += ["--find-links", str(resolved_wheel_dir)]
    if offline:
        install.append("--no-index")
    install += ["-r", "requirements.txt"]
    _run(install)
    probe = "; ".join(
        ["import importlib.metadata as m"]
        + [f"assert m.version({name!r}) == {version!r}" for name, version in REQUIRED_DISTRIBUTIONS.items()]
    )
    _run([str(venv_python), "-c", probe])
    print(f"[完成] 虚拟环境：{target}")
    print(f"[Python] {subprocess.check_output([str(venv_python), '--version'], text=True).strip()}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化 Spider Python 虚拟环境")
    parser.add_argument("--python", help="指定 Python 3.11+ 可执行文件")
    parser.add_argument("--venv", type=Path, default=DEFAULT_VENV)
    parser.add_argument("--recreate", action="store_true", help="删除并重建虚拟环境")
    parser.add_argument("--skip-pip-upgrade", action="store_true")
    parser.add_argument("--wheel-dir", type=Path, help="可选的本地 Wheel 目录")
    parser.add_argument("--offline", action="store_true", help="只使用 --wheel-dir，不访问包索引")
    args = parser.parse_args()
    try:
        execute(
            python=args.python,
            venv=args.venv,
            recreate=args.recreate,
            skip_pip_upgrade=args.skip_pip_upgrade,
            wheel_dir=args.wheel_dir,
            offline=args.offline,
        )
        return 0
    except (EnvironmentInitError, OSError, subprocess.SubprocessError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
