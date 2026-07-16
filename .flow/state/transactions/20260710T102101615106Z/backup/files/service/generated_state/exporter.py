from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Iterable

from configs.path import PROJECT_ROOT
from service.generated_state.common import (
    GeneratedStateError,
    _ensure_regular_tree,
    _file_record,
    _is_excluded,
    _iter_files,
    _read_project_version,
    _utc_now,
)
from service.generated_state.config import GeneratedStateConfig, load_generated_state_config
from service.generated_state.repository import _resolve_revision

def _copy_export_path(
    project_root: Path,
    destination_root: Path,
    relative: str,
    exclude_patterns: Iterable[str],
) -> None:
    source = project_root / relative
    if not source.exists():
        raise GeneratedStateError(f"generated-state source path is missing: {source}")
    _ensure_regular_tree(source)
    if source.is_file():
        if _is_excluded(relative, exclude_patterns):
            raise GeneratedStateError(f"required export path is excluded: {relative}")
        target = destination_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return
    for child in sorted(source.rglob("*")):
        child_relative = child.relative_to(project_root).as_posix()
        if child.is_symlink():
            raise GeneratedStateError(f"generated-state does not allow symlinks: {child}")
        if child.is_dir() or _is_excluded(child_relative, exclude_patterns):
            continue
        target = destination_root / child_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(child, target)

def _copy_report(source: Path, destination_root: Path, name: str) -> dict[str, Any]:
    if not source.is_file() or source.is_symlink():
        raise GeneratedStateError(f"report file does not exist or is not regular: {source}")
    relative = Path(".generated-state") / "reports" / name
    target = destination_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return _file_record(destination_root, target)

def _spider_extension(project_root: Path) -> dict[str, Any]:
    package_source_dir = project_root / "packages" / "kancolle-data"
    generated_package_dir = project_root / "dist" / "packages" / "kancolle-data"
    package_path = package_source_dir / "package.json"
    if not package_path.exists():
        package_path = generated_package_dir / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package_manifest = json.loads((generated_package_dir / "manifest.json").read_text(encoding="utf-8"))
    datasets = package_manifest.get("datasets", {})
    statuses = {
        name: value.get("status")
        for name, value in datasets.items()
        if isinstance(value, dict) and "status" in value
    }
    return {
        "package": {
            "name": str(package.get("name", "")),
            "version": str(package.get("version", "")),
        },
        "dataGeneratedAt": package_manifest.get("generatedAt"),
        "datasetStatuses": statuses,
    }

def export_generated_state(
    *,
    project_root: Path | None = None,
    output_dir: Path,
    base_ref: str,
    base_commit: str | None = None,
    config: GeneratedStateConfig | None = None,
    verification_report: Path | None = None,
    npm_audit: Path | None = None,
    build_id: str | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    root = (project_root or Path(PROJECT_ROOT)).resolve()
    destination = output_dir.expanduser().resolve()
    state_config = config or load_generated_state_config()
    if not base_ref.strip():
        raise GeneratedStateError("base ref cannot be empty")

    if destination == root or destination in root.parents:
        raise GeneratedStateError(
            "generated-state output cannot replace project root or one of its ancestors"
        )
    if destination.is_symlink():
        raise GeneratedStateError(f"output path cannot be a symlink: {destination}")
    for relative in state_config.export_paths:
        source = (root / relative).resolve()
        if destination == source or source in destination.parents:
            raise GeneratedStateError(
                f"generated-state output cannot be inside an export path: {relative}"
            )
    if destination.exists():
        if not destination.is_dir():
            raise GeneratedStateError(f"output path is not a directory: {destination}")
        if any(destination.iterdir()):
            if not replace:
                raise GeneratedStateError(
                    f"output directory is not empty: {destination}; use --replace"
                )
            shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)

    try:
        for relative in state_config.export_paths:
            _copy_export_path(
                root,
                destination,
                relative,
                state_config.exclude_patterns,
            )

        output_records = [
            _file_record(destination, path)
            for path in _iter_files(destination, state_config.export_paths)
        ]
        if not output_records:
            raise GeneratedStateError("generated-state export produced no files")
        revision = _resolve_revision(root, base_ref, base_commit)
        now = _utc_now()
        effective_build_id = (build_id or f"{now.strftime('%Y%m%dT%H%M%SZ')}-{revision[:12]}").strip()
        if not effective_build_id or any(char in effective_build_id for char in ("/", "\\", "\n", "\r")):
            raise GeneratedStateError(f"unsafe build id: {effective_build_id!r}")
        reports: list[dict[str, Any]] = []
        if verification_report:
            reports.append(
                {
                    "kind": "verification",
                    **_copy_report(verification_report, destination, "verification-report.json"),
                }
            )
        if npm_audit:
            reports.append(
                {
                    "kind": "npm-audit",
                    **_copy_report(npm_audit, destination, "npm-audit.json"),
                }
            )

        manifest = {
            "schemaVersion": 1,
            "stateId": state_config.state_id,
            "role": state_config.role,
            "buildId": effective_build_id,
            "baseRevision": {
                "type": "git",
                "ref": base_ref,
                "commit": revision,
            },
            "generator": {
                "project": "kancolle-item-improvement-spider",
                "projectVersion": _read_project_version(root),
                "contractVersion": 1,
            },
            "generatedAt": now.isoformat().replace("+00:00", "Z"),
            "outputs": output_records,
            "reports": reports,
            "extensions": {
                "spider.kancolle": _spider_extension(root),
            },
        }
        manifest_path = destination / state_config.manifest_path
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {
            "schemaVersion": 1,
            "stateId": state_config.state_id,
            "buildId": effective_build_id,
            "outputDir": str(destination),
            "manifest": str(manifest_path),
            "baseCommit": revision,
            "outputCount": len(output_records),
        }
    except Exception:
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        raise

