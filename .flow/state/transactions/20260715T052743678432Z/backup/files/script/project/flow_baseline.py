from __future__ import annotations

"""Flow-owned baseline and content identity helpers.

Git is deliberately treated as storage/audit only.  Update compatibility is
proved with Flow content identity: deterministic project-owned file inventory,
dependency lock hash, artifact hash and check receipt hash.
"""

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ownership import candidate_paths_for_identity, classify_path

BASELINE_PATH = Path(".flow/baseline.json")
CONTENT_SCHEME = "flow-content-sha256"
LEGACY_CONTENT_SCHEME = "project-owned-sha256"
LOCK_SCHEME = "flow-lock-sha256"
QUICK_RECEIPT_PATHS = (
    Path(".flow/state/checks/quick.json"),
    Path(".flow/state/checks/before.json"),
)
DEPENDENCY_FILES = (
    "mise.toml",
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "packages/kancolle-data/package.json",
    "packages/kancolle-data/package-lock.json",
)


@dataclass(frozen=True)
class FileRecord:
    path: str
    sha256: str
    mode: str
    sizeBytes: int


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prefixed(value: str | None) -> str | None:
    if not value:
        return None
    return value if value.startswith("sha256:") else f"sha256:{value}"


def _raw(value: str | None) -> str | None:
    if not value:
        return None
    return value.removeprefix("sha256:")


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    return (completed.stdout or "").strip() if completed.returncode == 0 else ""


def baseline_path(root: Path) -> Path:
    return root / BASELINE_PATH


def file_mode(path: Path) -> str:
    return "100755" if path.stat().st_mode & 0o111 else "100644"


def content_files(root: Path) -> list[FileRecord]:
    records: list[FileRecord] = []
    for relative in candidate_paths_for_identity(root):
        path = root / relative
        if not path.is_file() or path.is_symlink():
            continue
        records.append(
            FileRecord(
                path=relative,
                sha256=_sha256_file(path),
                mode=file_mode(path),
                sizeBytes=path.stat().st_size,
            )
        )
    return sorted(records, key=lambda item: item.path)


def hash_file_records(records: list[FileRecord] | list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in records:
        path = str(item.path if isinstance(item, FileRecord) else item["path"])
        mode = str(item.mode if isinstance(item, FileRecord) else item["mode"])
        sha256 = str(item.sha256 if isinstance(item, FileRecord) else item["sha256"])
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(mode.encode("ascii"))
        digest.update(b"\0")
        digest.update(sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def content_hash(root: Path) -> str:
    return hash_file_records(content_files(root))


def content_identity(root: Path) -> dict[str, str]:
    return {"scheme": CONTENT_SCHEME, "value": content_hash(root)}


def dependency_files(root: Path) -> list[FileRecord]:
    records: list[FileRecord] = []
    for relative in DEPENDENCY_FILES:
        path = root / relative
        if path.is_file() and classify_path(root, relative) == "project-owned":
            records.append(
                FileRecord(
                    path=relative,
                    sha256=_sha256_file(path),
                    mode=file_mode(path),
                    sizeBytes=path.stat().st_size,
                )
            )
    return sorted(records, key=lambda item: item.path)


def lock_hash(root: Path) -> str:
    return hash_file_records(dependency_files(root))


def latest_quick_receipt(root: Path) -> tuple[Path | None, dict[str, Any] | None, str | None]:
    for relative in QUICK_RECEIPT_PATHS:
        path = root / relative
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        return path, value, _sha256_file(path)
    return None, None, None


def receipt_binds_current_content(root: Path, receipt: dict[str, Any] | None) -> bool:
    if not receipt:
        return False
    expected_content = _raw(str(receipt.get("contentHash") or ""))
    expected_lock = _raw(str(receipt.get("lockHash") or ""))
    return expected_content == content_hash(root) and expected_lock == lock_hash(root)


def payload_hash(files: list[dict[str, Any]], delete: list[str]) -> str:
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda value: str(value["path"])):
        digest.update(str(item["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item.get("mode", "100644")).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(item["sha256"]).encode("ascii"))
        digest.update(b"\n")
    digest.update(b"--delete--\n")
    for relative in sorted(delete):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _records_json(records: list[FileRecord]) -> list[dict[str, Any]]:
    return [
        {
            "path": item.path,
            "sha256": item.sha256,
            "mode": item.mode,
            "sizeBytes": item.sizeBytes,
        }
        for item in records
    ]


def build_state(
    root: Path,
    *,
    version: str,
    package_sha256: str | None = None,
    payload_sha256: str | None = None,
    quick_receipt_sha256: str | None = None,
    source: str = "current-worktree",
) -> dict[str, Any]:
    files = content_files(root)
    dependencies = dependency_files(root)
    content = hash_file_records(files)
    locks = hash_file_records(dependencies)
    state = {
        "schemaVersion": 1,
        "project": "kancolle-item-improvement-spider",
        "version": version,
        "baselineId": f"{version}@flow-content:{content[:12]}",
        "contentIdentity": {"scheme": CONTENT_SCHEME, "value": content},
        "contentHash": _prefixed(content),
        "lockIdentity": {"scheme": LOCK_SCHEME, "value": locks},
        "lockHash": _prefixed(locks),
        "quickReceiptHash": _prefixed(quick_receipt_sha256),
        "artifactHash": _prefixed(package_sha256),
        "payloadHash": _prefixed(payload_sha256),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "excludedFromContentHash": [BASELINE_PATH.as_posix()],
        "files": _records_json(files),
        "dependencyFiles": _records_json(dependencies),
    }
    state["gitAudit"] = {
        "commit": _git(root, "rev-parse", "HEAD"),
        "tree": _git(root, "rev-parse", "HEAD^{tree}"),
        "branch": _git(root, "branch", "--show-current"),
    }
    return state


def read_state(root: Path) -> dict[str, Any] | None:
    path = baseline_path(root)
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Flow baseline 根节点必须是对象：{path}")
    return value


def write_state(root: Path, state: dict[str, Any]) -> Path:
    path = baseline_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def write_current_state(root: Path, *, source: str = "manual") -> Path:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    receipt_path, receipt, receipt_hash = latest_quick_receipt(root)
    state = build_state(
        root,
        version=version,
        quick_receipt_sha256=receipt_hash if receipt_binds_current_content(root, receipt) else None,
        source=source,
    )
    if receipt_path is not None:
        state["quickReceiptPath"] = receipt_path.relative_to(root).as_posix()
    return write_state(root, state)


def assert_state_matches_current(root: Path, state: dict[str, Any] | None = None) -> None:
    value = state if state is not None else read_state(root)
    if value is None:
        raise RuntimeError("缺少 Flow baseline：请先应用含 baseline 的更新，或执行 baseline 初始化")
    expected = _raw(str(value.get("contentHash") or value.get("contentIdentity", {}).get("value") or ""))
    actual = content_hash(root)
    if expected != actual:
        raise RuntimeError(f"Flow baseline 与当前内容不一致：current={actual} baseline={expected}")
