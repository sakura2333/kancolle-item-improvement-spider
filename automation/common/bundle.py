from __future__ import annotations

import hashlib
import json
import shutil
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


class BundleError(RuntimeError):
    pass


_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: str) -> Path:
    posix = PurePosixPath(value)
    if posix.is_absolute() or ".." in posix.parts or not posix.parts:
        raise BundleError(f"invalid bundle path: {value!r}")
    return Path(*posix.parts)


def file_records(root: Path, *, exclude: set[str] | None = None) -> list[dict]:
    exclude = exclude or set()
    records: list[dict] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in exclude:
            continue
        records.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "sizeBytes": path.stat().st_size,
            }
        )
    return records


def content_hash(records: list[dict]) -> str:
    digest = hashlib.sha256()
    for item in sorted(records, key=lambda row: str(row["path"])):
        digest.update(str(item["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def write_manifest(output: Path, *, kind: str, project_id: str, commit: str, metadata: dict | None = None) -> dict:
    if not _COMMIT_RE.fullmatch(commit):
        raise BundleError(f"invalid bundle Git commit: {commit!r}")
    records = file_records(output, exclude={"bundle-manifest.json"})
    payload = {
        "schemaVersion": 1,
        "kind": kind,
        "projectId": project_id,
        "commit": commit,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "contentHash": f"sha256:{content_hash(records)}",
        "files": records,
        "metadata": metadata or {},
    }
    (output / "bundle-manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def verify_manifest(bundle: Path, *, expected_kind: str | None = None, expected_project: str | None = None) -> dict:
    path = bundle / "bundle-manifest.json"
    if not path.is_file():
        raise BundleError(f"bundle manifest missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1:
        raise BundleError("unsupported bundle manifest schema")
    if expected_kind and payload.get("kind") != expected_kind:
        raise BundleError(f"bundle kind mismatch: {payload.get('kind')} != {expected_kind}")
    if expected_project and payload.get("projectId") != expected_project:
        raise BundleError("bundle project identity mismatch")
    if not _COMMIT_RE.fullmatch(str(payload.get("commit", ""))):
        raise BundleError("bundle Git commit is invalid")
    declared = payload.get("files")
    if not isinstance(declared, list):
        raise BundleError("bundle file list is invalid")
    actual = file_records(bundle, exclude={"bundle-manifest.json"})
    if actual != declared:
        raise BundleError("bundle file inventory or content hash changed")
    if payload.get("contentHash") != f"sha256:{content_hash(actual)}":
        raise BundleError("bundle contentHash mismatch")
    for item in declared:
        _safe_relative(str(item["path"]))
    return payload


def copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        return
    if source.is_symlink():
        raise BundleError(f"bundle source cannot be a symlink: {source}")
    if source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise BundleError(f"bundle source cannot contain symlinks: {path}")
        relative = path.relative_to(source)
        destination = target / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
