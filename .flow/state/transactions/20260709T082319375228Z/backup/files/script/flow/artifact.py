from __future__ import annotations

import json
from pathlib import Path

from .common import sha256_file


def sidecar_path(artifact: Path) -> Path:
    return artifact.with_name(artifact.name + ".flow.json")


def write_sidecar(
    artifact: Path,
    *,
    package_type: str,
    package_id: str,
    project_id: str,
    version: str | None = None,
    base_version: str | None = None,
    target_version: str | None = None,
    base_identity: dict | None = None,
    target_identity: dict | None = None,
    schema_version: int = 1,
    extra: dict | None = None,
) -> Path:
    value = {
        "schemaVersion": schema_version,
        "artifactFile": artifact.name,
        "packageType": package_type,
        "packageId": package_id,
        "projectId": project_id,
        "sha256": sha256_file(artifact),
    }
    if version is not None:
        value["version"] = version
    if base_version is not None:
        value["baseVersion"] = base_version
    if target_version is not None:
        value["targetVersion"] = target_version
    if base_identity is not None:
        value["baseIdentity"] = base_identity
    if target_identity is not None:
        value["targetIdentity"] = target_identity
    if extra:
        value.update(extra)
    path = sidecar_path(artifact)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def read_sidecar(path: Path) -> dict:
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Sidecar 根节点必须是对象：{path}")
    required = {"schemaVersion", "artifactFile", "packageType", "packageId", "projectId", "sha256"}
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f"Sidecar 缺少字段：{missing}")
    if value["schemaVersion"] not in {1, 2}:
        raise ValueError("不支持的 Sidecar schemaVersion")
    return value


def verify_sidecar(sidecar: Path) -> tuple[Path, dict]:
    value = read_sidecar(sidecar)
    artifact = sidecar.parent / str(value["artifactFile"])
    if artifact.name != value["artifactFile"] or not artifact.is_file():
        raise ValueError(f"Sidecar 对应 Artifact 不存在：{artifact}")
    digest = sha256_file(artifact)
    if digest != value["sha256"]:
        raise ValueError(f"Artifact SHA-256 不一致：{artifact.name}")
    return artifact, value
