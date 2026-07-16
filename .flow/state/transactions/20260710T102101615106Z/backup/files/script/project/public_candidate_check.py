from __future__ import annotations

"""Mechanical checks for the AI-reviewed public candidate worktree."""

import json
from pathlib import Path, PurePosixPath
from typing import Any


class PublicCandidateError(RuntimeError):
    pass


def _safe_relative(value: str) -> Path:
    pure = PurePosixPath(value)
    if not value or pure.is_absolute() or ".." in pure.parts or ".git" in pure.parts:
        raise PublicCandidateError(f"公开内容清单包含不安全路径：{value!r}")
    return Path(*pure.parts)


def inspect_candidate(worktree: Path, config: dict) -> dict[str, Any]:
    stable = config["stable"]
    manifest_rel = _safe_relative(str(stable["contentManifest"]["path"]))
    manifest_path = worktree / manifest_rel
    if not manifest_path.is_file():
        raise PublicCandidateError(f"公共候选缺少 {manifest_rel.as_posix()}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublicCandidateError(f"公共内容清单无法读取：{exc}") from exc
    if manifest.get("schemaVersion") != 1 or manifest.get("project") != config["project"]["id"]:
        raise PublicCandidateError("公共内容清单身份无效")
    if manifest.get("migrationId") != stable["contentManifest"]["migrationId"]:
        raise PublicCandidateError("公共内容清单 Migration ID 不一致")
    managed = manifest.get("managedFiles")
    if not isinstance(managed, list) or not managed:
        raise PublicCandidateError("公共内容清单缺少 managedFiles")
    normalized: list[str] = []
    for item in managed:
        if not isinstance(item, str):
            raise PublicCandidateError("公共内容清单路径类型无效")
        relative = _safe_relative(item)
        if not (worktree / relative).is_file():
            raise PublicCandidateError(f"公共内容清单引用不存在文件：{item}")
        normalized.append(relative.as_posix())
    if len(normalized) != len(set(normalized)):
        raise PublicCandidateError("公共内容清单包含重复路径")
    internal = stable["internalOnly"]
    from .stable_command import _matches  # avoid duplicating project glob semantics
    leaked = [item for item in normalized if any(_matches(item, pattern) for pattern in internal)]
    if leaked:
        raise PublicCandidateError("AI 候选包含内部路径：\n" + "\n".join(leaked))
    missing = [item for item in stable["required"] if item not in normalized]
    if missing:
        raise PublicCandidateError(f"AI 候选缺少必要公开文件：{missing}")
    return {"manifest": manifest, "managedFiles": sorted(normalized)}
