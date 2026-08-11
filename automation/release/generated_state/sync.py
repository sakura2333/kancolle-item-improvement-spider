from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

from automation.release.generated_state.config import GeneratedStateConfig, load_generated_state_config
from automation.release.generated_state.manifest import GeneratedStateError, verify_generated_state


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise GeneratedStateError(f"baseline path escapes root: {relative}") from exc
    return path


def _assert_regular_tree(path: Path) -> None:
    if path.is_symlink():
        raise GeneratedStateError(f"baseline synchronization does not allow symlinks: {path}")
    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_symlink():
                raise GeneratedStateError(
                    f"baseline synchronization does not allow symlinks: {child}"
                )


def _files(root: Path, relative: str) -> dict[str, Path]:
    path = _safe_path(root, relative)
    if not path.exists():
        raise GeneratedStateError(f"baseline path is missing: {relative}")
    _assert_regular_tree(path)
    if path.is_file():
        return {relative: path}
    return {
        child.relative_to(root).as_posix(): child
        for child in sorted(path.rglob("*"))
        if child.is_file()
    }


def build_sync_report(
    *,
    state_root: Path,
    project_root: Path,
    config: GeneratedStateConfig | None = None,
) -> dict[str, Any]:
    source_root = state_root.expanduser().resolve()
    target_root = project_root.expanduser().resolve()
    state_config = config or load_generated_state_config()
    verification = verify_generated_state(source_root, state_config)
    added: list[str] = []
    modified: list[str] = []
    deleted: list[str] = []
    unchanged = 0

    for relative in state_config.baseline_sync_paths:
        source_files = _files(source_root, relative)
        target_path = _safe_path(target_root, relative)
        target_files = _files(target_root, relative) if target_path.exists() else {}
        for path in sorted(source_files.keys() | target_files.keys()):
            source = source_files.get(path)
            target = target_files.get(path)
            if source is None:
                deleted.append(path)
            elif target is None:
                added.append(path)
            elif source.stat().st_size != target.stat().st_size or _sha256(source) != _sha256(target):
                modified.append(path)
            else:
                unchanged += 1

    return {
        "schemaVersion": 1,
        "stateId": verification["stateId"],
        "buildId": verification["buildId"],
        "baseCommit": verification["baseCommit"],
        "paths": list(state_config.baseline_sync_paths),
        "changes": {
            "added": added,
            "modified": modified,
            "deleted": deleted,
            "unchangedCount": unchanged,
        },
        "hasChanges": bool(added or modified or deleted),
    }


def _copy_for_stage(source: Path, target: Path) -> None:
    _assert_regular_tree(source)
    if source.is_dir():
        shutil.copytree(source, target, copy_function=shutil.copy2)
    elif source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    else:
        raise GeneratedStateError(f"baseline source is missing: {source}")


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _validate_backup_location(
    backup_root: Path,
    *,
    state_root: Path,
    project_root: Path,
    baseline_paths: Iterable[str],
) -> None:
    if backup_root == state_root or state_root in backup_root.parents:
        raise GeneratedStateError("backup directory cannot be inside generated-state")
    for relative in baseline_paths:
        target = _safe_path(project_root, relative)
        if backup_root == target or target in backup_root.parents:
            raise GeneratedStateError(
                f"backup directory cannot be inside synchronized path: {relative}"
            )


def apply_generated_baseline(
    *,
    state_root: Path,
    project_root: Path,
    backup_dir: Path,
    config: GeneratedStateConfig | None = None,
) -> dict[str, Any]:
    source_root = state_root.expanduser().resolve()
    target_root = project_root.expanduser().resolve()
    state_config = config or load_generated_state_config()
    report = build_sync_report(
        state_root=source_root,
        project_root=target_root,
        config=state_config,
    )
    if not report["hasChanges"]:
        return {
            **report,
            "applied": False,
            "backupDir": None,
            "originallyPresent": {},
        }

    backup_root = backup_dir.expanduser().resolve()
    _validate_backup_location(
        backup_root,
        state_root=source_root,
        project_root=target_root,
        baseline_paths=state_config.baseline_sync_paths,
    )
    if backup_root.exists():
        if not backup_root.is_dir():
            raise GeneratedStateError(f"backup path is not a directory: {backup_root}")
        if any(backup_root.iterdir()):
            raise GeneratedStateError(f"backup directory is not empty: {backup_root}")
    backup_root.mkdir(parents=True, exist_ok=True)

    originals: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="generated-state-sync-", dir=target_root.parent) as temp:
        stage_root = Path(temp)
        for relative in state_config.baseline_sync_paths:
            source = _safe_path(source_root, relative)
            _copy_for_stage(source, stage_root / relative)
            target = _safe_path(target_root, relative)
            originals[relative] = target.exists()
            if target.exists():
                _copy_for_stage(target, backup_root / relative)

        touched: list[str] = []
        try:
            for relative in state_config.baseline_sync_paths:
                target = _safe_path(target_root, relative)
                touched.append(relative)
                _remove(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(stage_root / relative), str(target))
        except Exception:
            restore_generated_baseline(
                project_root=target_root,
                backup_dir=backup_root,
                paths=touched,
                originally_present=originals,
            )
            raise

    return {
        **report,
        "applied": True,
        "backupDir": str(backup_root),
        "originallyPresent": originals,
    }


def restore_generated_baseline(
    *,
    project_root: Path,
    backup_dir: Path,
    paths: Iterable[str],
    originally_present: dict[str, bool],
) -> None:
    target_root = project_root.expanduser().resolve()
    backup_root = backup_dir.expanduser().resolve()
    for relative in reversed(list(paths)):
        target = _safe_path(target_root, relative)
        _remove(target)
        backup = _safe_path(backup_root, relative)
        if originally_present.get(relative):
            if not backup.exists():
                raise GeneratedStateError(f"baseline backup is missing: {relative}")
            _copy_for_stage(backup, target)
