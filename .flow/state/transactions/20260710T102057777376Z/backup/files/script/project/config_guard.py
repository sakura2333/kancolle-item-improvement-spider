from __future__ import annotations

"""Configuration and generated-output boundary checks.

The guard keeps shared project configuration under ``configs/`` and prevents
machine-local runtime configuration from becoming project-owned code. It is a
project-level policy check, not a generic secret scanner.
"""

import fnmatch
import json
import re
import subprocess
from pathlib import Path

from script.project._common import ProjectCommandError

LOCAL_CONFIG_PATTERNS = (
    "configs/local/**",
    "configs/*.local.*",
    "configs/**/*.local.*",
    "configs/*.private.*",
    "configs/**/*.private.*",
    "configs/*.secret.*",
    "configs/**/*.secret.*",
    "configs/*cookie*",
    "configs/**/*cookie*",
    "configs/*session*",
    "configs/**/*session*",
    "configs/*token*",
    "configs/**/*token*",
)

CONFIG_LIKE_PATTERNS = (
    "**/config.example.json",
    "**/*.config.json",
    "**/*.config.yaml",
    "**/*.config.yml",
    "**/*.config.toml",
    "**/*-config.json",
    "**/*-config.yaml",
    "**/*-config.yml",
    "**/*-config.toml",
)

ALLOWED_CONFIG_OUTSIDE_CONFIGS = {
    ".flow/project.json",
    ".flow/local.example.json",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "mise.toml",
    "pyproject.toml",
    "uv.lock",
}

TEXT_CONFIG_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".ini", ".env"}
PLACEHOLDER_RE = re.compile(r"__(?:COOKIE|TOKEN|SECRET|PASSWORD|PASS|SESSION|PROXY|API_KEY|KEY|USER|USERNAME|HOST|PORT|PATH|BROWSER|CLIENT_SECRET)[A-Z0-9_]*__|REPLACE_ME|YOUR_[A-Z0-9_]+")
LOCAL_ABSOLUTE_PATH_RE = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/")

SKIP_DIRS = {
    ".git",
    ".venv",
    ".idea",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "log",
}


def _normalize(path: str | Path) -> str:
    return str(path).replace("\\", "/").strip("/")


def _matches(value: str, pattern: str) -> bool:
    value = _normalize(value)
    pattern = _normalize(pattern)
    base = pattern[:-3] if pattern.endswith("/**") else pattern
    return value == base or value.startswith(base + "/") or fnmatch.fnmatch(value, pattern)


def _is_template(relative: str) -> bool:
    value = _normalize(relative)
    name = Path(value).name.lower()
    return ".template." in name or name.endswith(".template.json") or name.endswith(".default.json")


def _is_allowed_flow_local_example(relative: str) -> bool:
    return _normalize(relative) == ".flow/local.example.json"


def _is_governed_config_path(relative: str) -> bool:
    value = _normalize(relative)
    return (
        value.startswith("configs/")
        or value in ALLOWED_CONFIG_OUTSIDE_CONFIGS
        or any(_matches(value, pattern) for pattern in CONFIG_LIKE_PATTERNS)
    )


def _tracked_paths(root: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            capture_output=True,
            check=True,
        )
    except Exception:
        values: list[str] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if any(part in SKIP_DIRS for part in Path(relative).parts):
                continue
            values.append(relative)
        return sorted(values)
    return sorted(item.decode("utf-8") for item in completed.stdout.split(b"\0") if item)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def _verify_json_file(root: Path, relative: str) -> None:
    path = root / relative
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectCommandError(f"配置 JSON 无效：{relative} 第 {exc.lineno} 行：{exc.msg}") from exc


def verify_config_governance(root: Path) -> None:
    root = root.resolve()
    paths = _tracked_paths(root)
    violations: list[str] = []

    for relative in paths:
        value = _normalize(relative)
        path = root / value
        if not path.is_file():
            continue

        if _is_template(value):
            if path.suffix.lower() == ".json":
                _verify_json_file(root, value)
            continue

        if any(_matches(value, pattern) for pattern in LOCAL_CONFIG_PATTERNS):
            violations.append(f"本地/私密配置不得提交：{value}")
            continue

        if value.startswith("configs/") and path.suffix.lower() == ".json":
            _verify_json_file(root, value)

        if not value.startswith("configs/") and value not in ALLOWED_CONFIG_OUTSIDE_CONFIGS:
            if any(_matches(value, pattern) for pattern in CONFIG_LIKE_PATTERNS):
                violations.append(f"项目配置默认值必须放在 configs/*.default.json：{value}")

        if path.suffix.lower() not in TEXT_CONFIG_SUFFIXES:
            continue
        if not _is_governed_config_path(value):
            continue
        text = _read_text(path)
        if text is None:
            continue
        if not _is_allowed_flow_local_example(value) and PLACEHOLDER_RE.search(text):
            violations.append(f"非模板配置不得包含占位符：{value}")
        if not _is_allowed_flow_local_example(value) and LOCAL_ABSOLUTE_PATH_RE.search(text):
            violations.append(f"非模板配置不得包含本机绝对路径：{value}")

    if violations:
        details = "\n".join(f"- {item}" for item in sorted(set(violations)))
        raise ProjectCommandError(f"配置治理校验失败：\n{details}")
