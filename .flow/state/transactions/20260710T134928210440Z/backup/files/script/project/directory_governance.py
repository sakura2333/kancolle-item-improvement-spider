from __future__ import annotations

import shutil
from pathlib import Path

from script.project._common import ProjectCommandError

DEPRECATED_LOCAL_ROOTS = ("data", "log", ".flow/packages")
DEPRECATED_PROJECT_ROOTS = ("configs/templates", "pojo", "service/generated_state")
DEPRECATED_CLEANUP_ROOTS = (*DEPRECATED_LOCAL_ROOTS, "service/generated_state")


def _contains_files(path: Path) -> bool:
    if path.is_symlink() or path.is_file():
        return True
    for child in path.rglob("*"):
        if "__pycache__" in child.parts or child.suffix in {".pyc", ".pyo"}:
            continue
        if child.is_file() or child.is_symlink():
            return True
    return False


def deprecated_paths(root: Path) -> list[str]:
    root = root.resolve()
    present = [relative for relative in DEPRECATED_LOCAL_ROOTS if (root / relative).exists() or (root / relative).is_symlink()]
    present.extend(
        relative
        for relative in DEPRECATED_PROJECT_ROOTS
        if (root / relative).exists() and _contains_files(root / relative)
    )
    return present


def verify_directory_governance(root: Path) -> None:
    present = deprecated_paths(root)
    if present:
        details = "\n".join(f"- {item}/" for item in present)
        raise ProjectCommandError(
            "目录治理校验失败；以下退役目录不得重新出现：\n" + details
        )


def remove_deprecated_local_dirs(root: Path) -> list[str]:
    """Remove retired local/generated roots without following symlinks.

    These roots have no authority in the current project layout. Source caches
    live under ``.flow/local/source-cache`` and generated output lives under
    ``dist``.  The function intentionally refuses symlinks so a malformed local
    path cannot redirect cleanup outside the project.
    """

    root = root.resolve()
    removed: list[str] = []
    for relative in DEPRECATED_CLEANUP_ROOTS:
        path = root / relative
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink():
            raise ProjectCommandError(f"拒绝清理指向项目外部的退役符号链接：{relative}")
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ProjectCommandError(f"退役目录不在项目根目录内：{relative}") from exc
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(relative)
    return removed
