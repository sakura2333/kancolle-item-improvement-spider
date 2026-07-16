from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


class LocalRuntimeMigrationError(RuntimeError):
    pass


LEGACY_ROOT = Path(".flow/local")
PUBLIC_ROOT = Path(".spider/local")
RECEIPT = PUBLIC_ROOT / "migrations/flow-local-to-spider-v1.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def migrate_legacy_runtime(root: Path) -> dict[str, object]:
    """Move the legacy public runtime tree out of Flow's control namespace.

    ``.flow/local.json`` is the internal Flow configuration file and is not
    touched.  Only the legacy directory ``.flow/local/**`` is migrated.
    Existing target files must be byte-identical; conflicts stop before any
    source deletion so operator data is never overwritten.
    """

    root = root.resolve()
    source_root = root / LEGACY_ROOT
    target_root = root / PUBLIC_ROOT
    receipt_path = root / RECEIPT
    if not source_root.exists():
        return {
            "schemaVersion": 1,
            "status": "not-needed",
            "legacyRoot": LEGACY_ROOT.as_posix(),
            "publicRoot": PUBLIC_ROOT.as_posix(),
            "migratedFileCount": 0,
            "receipt": RECEIPT.as_posix() if receipt_path.is_file() else None,
        }
    if source_root.is_symlink() or not source_root.is_dir():
        raise LocalRuntimeMigrationError(f"legacy runtime root is unsafe: {LEGACY_ROOT}")

    files: list[tuple[Path, Path, str]] = []
    conflicts: list[str] = []
    for source in sorted(source_root.rglob("*")):
        relative = source.relative_to(source_root)
        if source.is_symlink():
            raise LocalRuntimeMigrationError(f"legacy runtime contains symlink: {LEGACY_ROOT / relative}")
        if not source.is_file():
            continue
        target = target_root / relative
        digest = _sha256(source)
        if target.exists():
            if target.is_symlink() or not target.is_file() or _sha256(target) != digest:
                conflicts.append(relative.as_posix())
        files.append((source, target, digest))
    if conflicts:
        shown = ", ".join(conflicts[:20])
        raise LocalRuntimeMigrationError(
            "legacy and public runtime state conflict; no legacy files were removed: " + shown
        )

    copied = 0
    for source, target, _ in files:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(source, target)
            copied += 1
    shutil.rmtree(source_root)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "status": "completed",
        "migration": "flow-local-to-spider-v1",
        "legacyRoot": LEGACY_ROOT.as_posix(),
        "publicRoot": PUBLIC_ROOT.as_posix(),
        "migratedFileCount": len(files),
        "copiedFileCount": copied,
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "files": [
            {
                "path": target.relative_to(target_root).as_posix(),
                "sha256": digest,
            }
            for _, target, digest in files
        ],
    }
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**payload, "receipt": RECEIPT.as_posix()}


def migrate_for_project_command(root: Path) -> dict[str, object]:
    if os.getenv("FLOW_STAGING") == "1":
        return {
            "schemaVersion": 1,
            "status": "staging-skip",
            "legacyRoot": LEGACY_ROOT.as_posix(),
            "publicRoot": PUBLIC_ROOT.as_posix(),
            "migratedFileCount": 0,
            "receipt": None,
        }
    return migrate_legacy_runtime(root)
