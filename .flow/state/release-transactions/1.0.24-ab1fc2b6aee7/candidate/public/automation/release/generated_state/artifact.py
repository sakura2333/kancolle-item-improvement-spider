from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from automation.release.generated_state.config import GeneratedStateConfig, load_generated_state_config
from automation.release.generated_state.manifest import (
    GeneratedStateError,
    load_generated_state_manifest,
    verify_generated_state,
)

_MAX_ARCHIVE_FILES = 10_000
_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member_name(value: str) -> str:
    text = value.replace("\\", "/")
    path = PurePosixPath(text)
    if (
        not text
        or text.startswith("/")
        or path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or any(part == "" for part in path.parts)
    ):
        raise GeneratedStateError(f"unsafe generated-state archive member: {value!r}")
    return path.as_posix()


def _assert_external_path(path: Path, state_root: Path, *, label: str) -> None:
    resolved = path.expanduser().resolve()
    root = state_root.expanduser().resolve()
    if resolved == root or root in resolved.parents:
        raise GeneratedStateError(f"{label} cannot be stored inside generated-state: {resolved}")
    if resolved.is_symlink():
        raise GeneratedStateError(f"{label} cannot be a symlink: {resolved}")


def _iter_state_files(state_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(state_root.rglob("*")):
        if path.is_symlink():
            raise GeneratedStateError(f"generated-state artifact does not allow symlinks: {path}")
        if path.is_file():
            files.append(path)
    if not files:
        raise GeneratedStateError("generated-state artifact has no files")
    if len(files) > _MAX_ARCHIVE_FILES:
        raise GeneratedStateError(
            f"generated-state artifact contains too many files: {len(files)}"
        )
    total = sum(path.stat().st_size for path in files)
    if total > _MAX_ARCHIVE_BYTES:
        raise GeneratedStateError(
            f"generated-state artifact is too large: {total} bytes"
        )
    return files


def _zip_info(relative: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(relative, date_time=_FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.flag_bits |= 0x800
    return info


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def create_generated_state_artifact(
    *,
    state_root: Path,
    output_file: Path,
    receipt_file: Path | None = None,
    replace: bool = False,
    config: GeneratedStateConfig | None = None,
) -> dict[str, Any]:
    root = state_root.expanduser().resolve()
    state_config = config or load_generated_state_config()
    verification = verify_generated_state(root, state_config)
    manifest = load_generated_state_manifest(root, state_config)

    archive = output_file.expanduser().resolve()
    receipt = (
        receipt_file.expanduser().resolve()
        if receipt_file is not None
        else archive.with_name(f"{archive.name}.receipt.json")
    )
    _assert_external_path(archive, root, label="artifact")
    _assert_external_path(receipt, root, label="artifact receipt")
    if archive == receipt:
        raise GeneratedStateError("artifact and receipt paths must be different")
    for path, label in ((archive, "artifact"), (receipt, "artifact receipt")):
        if path.exists() and not replace:
            raise GeneratedStateError(f"{label} already exists: {path}; use --replace")
        if path.exists() and not path.is_file():
            raise GeneratedStateError(f"{label} path is not a regular file: {path}")

    files = _iter_state_files(root)
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name(f".{archive.name}.tmp-{os.getpid()}")
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=False,
        ) as target:
            for path in files:
                relative = _safe_member_name(path.relative_to(root).as_posix())
                target.writestr(_zip_info(relative), path.read_bytes())
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)

    manifest_path = root / state_config.manifest_path
    payload = {
        "schemaVersion": 1,
        "stateId": verification["stateId"],
        "buildId": verification["buildId"],
        "baseCommit": verification["baseCommit"],
        "artifact": {
            "format": "zip",
            "path": str(archive),
            "filename": archive.name,
            "sha256": _sha256(archive),
            "bytes": archive.stat().st_size,
            "fileCount": len(files),
        },
        "manifest": {
            "path": state_config.manifest_path,
            "sha256": _sha256(manifest_path),
        },
        "generator": manifest.get("generator"),
    }
    _write_receipt(receipt, payload)
    return {**payload, "receipt": str(receipt)}


def _validate_receipt(
    receipt_file: Path,
    *,
    archive: Path,
    verification: dict[str, Any],
    manifest_sha256: str,
    manifest_path: str,
    file_count: int,
) -> dict[str, Any]:
    if not receipt_file.is_file() or receipt_file.is_symlink():
        raise GeneratedStateError(
            f"generated-state receipt is missing or not regular: {receipt_file}"
        )
    try:
        payload = json.loads(receipt_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GeneratedStateError(f"generated-state receipt is missing: {receipt_file}") from exc
    except json.JSONDecodeError as exc:
        raise GeneratedStateError(f"invalid generated-state receipt: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise GeneratedStateError("unsupported generated-state receipt schema")
    expected = {
        "stateId": verification["stateId"],
        "buildId": verification["buildId"],
        "baseCommit": verification["baseCommit"],
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise GeneratedStateError(f"generated-state receipt {field} mismatch")
    artifact = payload.get("artifact")
    if not isinstance(artifact, dict) or artifact.get("format") != "zip":
        raise GeneratedStateError("generated-state receipt has invalid artifact metadata")
    if artifact.get("filename") != archive.name:
        raise GeneratedStateError("generated-state artifact filename does not match receipt")
    if artifact.get("sha256") != _sha256(archive):
        raise GeneratedStateError("generated-state artifact sha256 does not match receipt")
    if artifact.get("bytes") != archive.stat().st_size:
        raise GeneratedStateError("generated-state artifact size does not match receipt")
    if artifact.get("fileCount") != file_count:
        raise GeneratedStateError("generated-state artifact file count does not match receipt")
    manifest = payload.get("manifest")
    if (
        not isinstance(manifest, dict)
        or manifest.get("path") != manifest_path
        or manifest.get("sha256") != manifest_sha256
    ):
        raise GeneratedStateError("generated-state manifest metadata does not match receipt")
    return payload


def verify_generated_state_artifact(
    *,
    archive_file: Path,
    receipt_file: Path | None = None,
    config: GeneratedStateConfig | None = None,
) -> dict[str, Any]:
    archive = archive_file.expanduser().resolve()
    if not archive.is_file() or archive.is_symlink():
        raise GeneratedStateError(f"generated-state artifact is missing or not regular: {archive}")
    state_config = config or load_generated_state_config()

    with tempfile.TemporaryDirectory(prefix="generated-state-artifact-") as temporary:
        extracted = Path(temporary)
        try:
            with zipfile.ZipFile(archive, "r") as source:
                members = source.infolist()
                if not members:
                    raise GeneratedStateError("generated-state artifact is empty")
                if len(members) > _MAX_ARCHIVE_FILES:
                    raise GeneratedStateError(
                        f"generated-state artifact contains too many members: {len(members)}"
                    )
                total_size = 0
                seen: set[str] = set()
                for member in members:
                    name = _safe_member_name(member.filename)
                    if name in seen:
                        raise GeneratedStateError(
                            f"duplicate generated-state archive member: {name}"
                        )
                    seen.add(name)
                    mode = (member.external_attr >> 16) & 0xFFFF
                    if stat.S_ISLNK(mode):
                        raise GeneratedStateError(
                            f"generated-state artifact does not allow symlinks: {name}"
                        )
                    if member.is_dir():
                        continue
                    total_size += member.file_size
                    if total_size > _MAX_ARCHIVE_BYTES:
                        raise GeneratedStateError(
                            f"generated-state artifact expands beyond {_MAX_ARCHIVE_BYTES} bytes"
                        )
                    target = extracted / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(member, "r") as input_stream, target.open("wb") as output_stream:
                        shutil.copyfileobj(input_stream, output_stream)
        except zipfile.BadZipFile as exc:
            raise GeneratedStateError(f"invalid generated-state zip artifact: {exc}") from exc

        verification = verify_generated_state(extracted, state_config)
        manifest_sha256 = _sha256(extracted / state_config.manifest_path)
        extracted_file_count = sum(1 for path in extracted.rglob("*") if path.is_file())
        receipt_payload = None
        if receipt_file is not None:
            receipt_payload = _validate_receipt(
                receipt_file.expanduser().resolve(),
                archive=archive,
                verification=verification,
                manifest_sha256=manifest_sha256,
                manifest_path=state_config.manifest_path,
                file_count=extracted_file_count,
            )
        return {
            **verification,
            "artifact": str(archive),
            "artifactSha256": _sha256(archive),
            "artifactBytes": archive.stat().st_size,
            "manifestSha256": manifest_sha256,
            "receiptVerified": receipt_payload is not None,
        }
