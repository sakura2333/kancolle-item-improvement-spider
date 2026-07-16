from __future__ import annotations

import fnmatch
import importlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .artifact import sidecar_path, verify_sidecar
from .common import load_json, now_id, run, sha256_file
from script.project.directory_governance import remove_deprecated_local_dirs


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candidate:
    path: Path
    sidecar: Path
    identity: dict
    manifest: dict

    @property
    def digest(self) -> str:
        return str(self.identity["sha256"])

    @property
    def project(self) -> str:
        return str(self.identity["projectId"])

    @property
    def from_version(self) -> str:
        return str(self.identity["baseVersion"])

    @property
    def to_version(self) -> str:
        return str(self.identity["targetVersion"])

    @property
    def base_identity(self) -> dict:
        return dict(self.identity["baseIdentity"])

    @property
    def target_identity(self) -> dict:
        return dict(self.identity["targetIdentity"])

    @property
    def package_version(self) -> int:
        value = self.identity.get("packageVersion") or self.manifest.get("packageVersion")
        if value in (None, ""):
            return 0
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise UpdateError(f"packageVersion 不是整数：{value}") from exc


_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def _version_key(value: str) -> tuple:
    match = _SEMVER.fullmatch(value)
    if not match:
        raise UpdateError(f"更新版本不是有效 SemVer：{value}")
    major, minor, patch = (int(match.group(i)) for i in (1, 2, 3))
    prerelease = match.group(4)
    if prerelease is None:
        return major, minor, patch, 1, ()
    parts = [(0, int(part)) if part.isdigit() else (1, part.casefold()) for part in prerelease.split(".")]
    return major, minor, patch, 0, tuple(parts)


def _result(status="成功", current="", completed=None, incomplete=None, next_step="", recovery="", exit_code=0):
    return {
        "status": status,
        "current": current,
        "completed": completed or [],
        "incomplete": incomplete or [],
        "next": next_step,
        "recovery": recovery,
        "exitCode": exit_code,
    }


def _git(root: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    if check and completed.returncode:
        raise UpdateError((completed.stderr or completed.stdout or "Git 命令失败").strip())
    return (completed.stdout or "").strip()


def _safe_path(value: str) -> PurePosixPath:
    pure = PurePosixPath(value)
    if not value or "\\" in value or pure.is_absolute() or ".." in pure.parts or value.endswith("/"):
        raise UpdateError(f"不安全的更新路径：{value}")
    return pure


def _matches(value: str, pattern: str) -> bool:
    value = value.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    return value == pattern.rstrip("/") or value.startswith(pattern.rstrip("/") + "/") or fnmatch.fnmatch(value, pattern)


def _identity_value(root: Path, scheme: str, config: dict | None = None) -> str:
    if scheme == "git-commit":
        return _git(root, "rev-parse", "HEAD")
    if scheme == "git-tree":
        return _git(root, "rev-parse", "HEAD^{tree}")
    provider = (config or {}).get("update", {}).get("identityProvider")
    if provider:
        module_name, function_name = str(provider).split(":", 1)
        function = getattr(importlib.import_module(module_name), function_name)
        try:
            return str(function(root, scheme))
        except Exception as exc:
            raise UpdateError(str(exc)) from exc
    raise UpdateError(f"Spider 更新器不支持内容身份算法：{scheme}")


def _inspect(artifact: Path, sidecar: Path, identity: dict) -> Candidate:
    if identity.get("packageType") != "update":
        raise UpdateError("Artifact 不是 update 包")
    required = {"baseVersion", "targetVersion", "baseIdentity", "targetIdentity"}
    missing = sorted(required - set(identity))
    if missing:
        raise UpdateError(f"更新 Sidecar 缺少字段：{missing}")
    if identity["baseIdentity"].get("scheme") != identity["targetIdentity"].get("scheme"):
        raise UpdateError("更新基线与目标身份算法必须一致")
    try:
        with zipfile.ZipFile(artifact) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise UpdateError("ZIP 存在重复成员")
            for member in archive.infolist():
                pure = PurePosixPath(member.filename)
                if pure.is_absolute() or ".." in pure.parts or "\\" in member.filename:
                    raise UpdateError(f"ZIP 路径越界：{member.filename}")
                mode = (member.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    raise UpdateError(f"ZIP 禁止符号链接：{member.filename}")
            if names.count("update-manifest.json") != 1:
                raise UpdateError("Artifact 内必须且只能包含一个 update-manifest.json")
            manifest = json.loads(archive.read("update-manifest.json").decode("utf-8"))
    except zipfile.BadZipFile as exc:
        raise UpdateError("不是有效 ZIP") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"更新 Manifest 无效：{exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") not in {1, 2}:
        raise UpdateError("不支持的 update-manifest")
    for key in ("projectId", "fromVersion", "toVersion", "baseIdentity", "targetIdentity", "files", "delete"):
        if key not in manifest:
            raise UpdateError(f"更新 Manifest 缺少 {key}")
    if manifest["projectId"] != identity["projectId"]:
        raise UpdateError("Manifest Project ID 与 Sidecar 不一致")
    if manifest["fromVersion"] != identity["baseVersion"] or manifest["toVersion"] != identity["targetVersion"]:
        raise UpdateError("Manifest 版本与 Sidecar 不一致")
    if manifest["baseIdentity"] != identity["baseIdentity"] or manifest["targetIdentity"] != identity["targetIdentity"]:
        raise UpdateError("Manifest 内容身份与 Sidecar 不一致")
    if identity.get("packageVersion") is not None and manifest.get("packageVersion") is not None:
        if int(identity["packageVersion"]) != int(manifest["packageVersion"]):
            raise UpdateError("Manifest packageVersion 与 Artifact 元数据不一致")
    if not isinstance(manifest["files"], list) or not isinstance(manifest["delete"], list):
        raise UpdateError("files/delete 必须是数组")
    seen: set[str] = set()
    with zipfile.ZipFile(artifact) as archive:
        names = archive.namelist()
        declared_members = {"update-manifest.json"}
        if names.count("flow-package.json") == 1:
            declared_members.add("flow-package.json")
        if manifest.get("schemaVersion") == 2 and names.count("quick-receipt.json") == 1:
            declared_members.add("quick-receipt.json")
            import hashlib
            receipt_digest = hashlib.sha256(archive.read("quick-receipt.json")).hexdigest()
            declared_receipt = str((manifest.get("to") or {}).get("quickReceiptHash") or manifest.get("quickReceiptHash") or "").removeprefix("sha256:")
            if declared_receipt and receipt_digest != declared_receipt:
                raise UpdateError("Quick Receipt 哈希不一致")
            try:
                receipt = json.loads(archive.read("quick-receipt.json").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise UpdateError(f"Quick Receipt 无效：{exc}") from exc
            if isinstance(receipt, dict):
                receipt_content = str(receipt.get("contentHash") or "").removeprefix("sha256:")
                target_value = str(manifest["targetIdentity"].get("value") or "")
                if receipt_content and receipt_content != target_value:
                    raise UpdateError("Quick Receipt 未绑定目标内容身份")
        for item in manifest["files"]:
            if not isinstance(item, dict):
                raise UpdateError("files 元素必须是对象")
            relative = str(item.get("path", ""))
            _safe_path(relative)
            digest = str(item.get("sha256", "")).lower()
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise UpdateError(f"文件 SHA-256 无效：{relative}")
            if relative in seen:
                raise UpdateError(f"重复路径：{relative}")
            seen.add(relative)
            member = f"payload/{relative}"
            declared_members.add(member)
            if names.count(member) != 1:
                raise UpdateError(f"Payload 必须且只能出现一次：{relative}")
        for relative in manifest["delete"]:
            if not isinstance(relative, str):
                raise UpdateError("delete 必须是字符串数组")
            _safe_path(relative)
            if relative in seen:
                raise UpdateError(f"同一路径同时修改和删除：{relative}")
            seen.add(relative)
        extras = sorted(name for name in names if not name.endswith("/") and name not in declared_members)
        if extras:
            raise UpdateError("ZIP 包含 Manifest 未声明文件：\n" + "\n".join(f"- {item}" for item in extras))
    if manifest.get("schemaVersion") == 2 and manifest.get("payloadHash"):
        from script.project.flow_baseline import payload_hash as flow_payload_hash

        expected_payload_hash = str(manifest["payloadHash"]).removeprefix("sha256:")
        actual_payload_hash = flow_payload_hash(manifest["files"], manifest["delete"])
        if actual_payload_hash != expected_payload_hash:
            raise UpdateError(f"Payload Manifest Hash 不一致：{actual_payload_hash} != {expected_payload_hash}")
    return Candidate(path=artifact, sidecar=sidecar, identity=identity, manifest=manifest)


def _local(root: Path) -> dict:
    path = root / ".flow/local.json"
    return load_json(path) if path.is_file() else {}


def _roots(root: Path, config: dict) -> tuple[Path, Path]:
    local = _local(root)
    download = Path(str(local.get("downloadRoot", "/Users/sakana/Downloads/GPT-Projects"))).expanduser().resolve()
    applied = download / ".flow-applied" / config["project"]["id"]
    return download, applied


def _package_dirs(root: Path, config: dict) -> list[Path]:
    local = _local(root)
    inbox, _applied = _roots(root, config)
    values = local.get("packageDirs") or []
    if isinstance(values, str):
        values = [values]
    # Only scan package input locations.  The applied archive is an audit store,
    # not an update inbox; scanning it can resurrect already-applied or obsolete
    # packages and forces humans/AI to reason about stale artifacts again.
    candidates = [inbox]
    for value in values:
        candidates.append(Path(str(value)).expanduser())
    result: list[Path] = []
    seen: set[str] = set()
    for item in candidates:
        resolved = item.resolve()
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            result.append(resolved)
    return result


def _embedded_identity(artifact: Path) -> dict:
    try:
        with zipfile.ZipFile(artifact) as archive:
            if archive.namelist().count("flow-package.json") == 1:
                value = json.loads(archive.read("flow-package.json").decode("utf-8"))
            else:
                manifest = json.loads(archive.read("update-manifest.json").decode("utf-8"))
                value = {
                    "schemaVersion": 3,
                    "artifactFile": artifact.name,
                    "packageType": "update",
                    "packageId": manifest.get("packageId") or artifact.stem,
                    "projectId": manifest["projectId"],
                    "sha256": sha256_file(artifact),
                    "baseVersion": manifest["fromVersion"],
                    "targetVersion": manifest["toVersion"],
                    "baseIdentity": manifest["baseIdentity"],
                    "targetIdentity": manifest["targetIdentity"],
                    "from": manifest.get("from"),
                    "to": manifest.get("to"),
                    "payloadHash": manifest.get("payloadHash"),
                }
                if manifest.get("packageVersion") is not None:
                    value["packageVersion"] = manifest.get("packageVersion")
    except (OSError, KeyError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"无法读取内嵌 Flow package metadata：{artifact}: {exc}") from exc
    if not isinstance(value, dict):
        raise UpdateError(f"内嵌 Flow package metadata 根节点必须是对象：{artifact}")
    value = dict(value)
    value["artifactFile"] = artifact.name
    value["sha256"] = sha256_file(artifact)
    return value


def _candidate_from_sidecar(sidecar: Path) -> Candidate:
    try:
        artifact, identity = verify_sidecar(sidecar)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise UpdateError(str(exc)) from exc
    return _inspect(artifact, sidecar, identity)


def _candidate_from_zip(artifact: Path) -> Candidate:
    identity = _embedded_identity(artifact)
    return _inspect(artifact, artifact, identity)


def _candidate_from_argument(value: str) -> Candidate:
    path = Path(value).expanduser().resolve()
    if path.name.endswith(".flow.json"):
        return _candidate_from_sidecar(path)
    sidecar = sidecar_path(path)
    if sidecar.is_file():
        return _candidate_from_sidecar(sidecar)
    if not path.is_file():
        raise UpdateError(f"更新包不存在：{path}")
    return _candidate_from_zip(path)


def _discover_candidates(root: Path, config: dict) -> tuple[list[Candidate], list[str]]:
    notes: list[str] = []
    candidates: list[Candidate] = []
    seen_artifacts: set[str] = set()
    project_id = str(config["project"]["id"])
    current_package_version = _baseline_package_version(root)
    ignored = {
        "missingDirs": 0,
        "otherProject": 0,
        "recovery": 0,
        "oldOrApplied": 0,
        "invalid": 0,
    }

    def record_invalid(name: str, exc: Exception) -> None:
        text = str(exc)
        if "Artifact 不是 update 包" in text or "flow.recovery" in text or "recovery" in name.lower():
            ignored["recovery"] += 1
            return
        ignored["invalid"] += 1

    for folder in _package_dirs(root, config):
        if not folder.is_dir():
            ignored["missingDirs"] += 1
            continue
        for sidecar in sorted(folder.glob("*.zip.flow.json")) + sorted(folder.glob("*.flow.json")):
            if sidecar.name.endswith(".zip.flow.json"):
                artifact_name = sidecar.name.removesuffix(".flow.json")
                parsed_version = _parse_package_version_from_name(artifact_name)
                if parsed_version and parsed_version <= current_package_version:
                    ignored["oldOrApplied"] += 1
                    continue
            try:
                candidate = _candidate_from_sidecar(sidecar)
            except UpdateError as exc:
                if project_id in sidecar.name:
                    record_invalid(sidecar.name, exc)
                else:
                    ignored["otherProject"] += 1
                continue
            if candidate.project != project_id:
                ignored["otherProject"] += 1
                continue
            if candidate.package_version and candidate.package_version <= current_package_version:
                ignored["oldOrApplied"] += 1
                continue
            key = str(candidate.path.resolve())
            if key not in seen_artifacts:
                seen_artifacts.add(key)
                candidates.append(candidate)
        for artifact in sorted(folder.glob("*.zip")):
            key = str(artifact.resolve())
            if key in seen_artifacts:
                continue
            if project_id not in artifact.name:
                ignored["otherProject"] += 1
                continue
            parsed_version = _parse_package_version_from_name(artifact.name)
            if parsed_version and parsed_version <= current_package_version:
                ignored["oldOrApplied"] += 1
                continue
            try:
                candidate = _candidate_from_argument(str(artifact))
            except UpdateError as exc:
                record_invalid(artifact.name, exc)
                continue
            if candidate.project != project_id:
                ignored["otherProject"] += 1
                continue
            if candidate.package_version and candidate.package_version <= current_package_version:
                ignored["oldOrApplied"] += 1
                continue
            seen_artifacts.add(key)
            candidates.append(candidate)
    summary = []
    if ignored["otherProject"]:
        summary.append(f"非本项目包 {ignored['otherProject']} 个")
    if ignored["recovery"]:
        summary.append(f"recovery/非 update 包 {ignored['recovery']} 个")
    if ignored["oldOrApplied"]:
        summary.append(f"低序号或已应用包 {ignored['oldOrApplied']} 个")
    if ignored["invalid"]:
        summary.append(f"无效包 {ignored['invalid']} 个")
    if ignored["missingDirs"]:
        summary.append(f"不存在的包目录 {ignored['missingDirs']} 个")
    if summary:
        notes.append("扫描忽略：" + "，".join(summary))
    return candidates, notes


def _discover_next_candidates(root: Path, config: dict) -> tuple[list[Candidate], list[str]]:
    current_package_version = _baseline_package_version(root)
    if current_package_version <= 0:
        # Legacy/migration projects may not have a packageVersion yet.  Keep the
        # broader contentHash discovery path only for that bootstrap state.
        return _discover_candidates(root, config)

    next_package_version = current_package_version + 1
    project_id = str(config["project"]["id"])
    artifact_name = f"{project_id}-{next_package_version}.zip"
    notes = [
        f"更新索引：packageVersion {current_package_version} → {next_package_version}",
        f"候选文件：{artifact_name}",
    ]
    candidates: list[Candidate] = []
    invalid: list[str] = []
    for folder in _package_dirs(root, config):
        artifact = folder / artifact_name
        sidecar = sidecar_path(artifact)
        if not artifact.is_file():
            if sidecar.is_file():
                invalid.append(f"{sidecar}: 缺少对应 ZIP")
            continue
        try:
            candidate = _candidate_from_argument(str(artifact))
        except UpdateError as exc:
            invalid.append(f"{artifact}: {exc}")
            continue
        if candidate.path.resolve() != artifact.resolve():
            invalid.append(
                f"{artifact}: sidecar artifactFile 指向 {candidate.path.name}，"
                f"必须指向 canonical 文件名"
            )
            continue
        if candidate.project != project_id:
            invalid.append(f"{artifact}: projectId={candidate.project}")
            continue
        if candidate.package_version != next_package_version:
            invalid.append(
                f"{artifact}: packageVersion={candidate.package_version or 'missing'}，"
                f"expected={next_package_version}"
            )
            continue
        candidates.append(candidate)

    if invalid:
        raise UpdateError(
            f"下一版本 {next_package_version} 的 canonical 更新包无效：\n"
            + "\n".join(f"- {item}" for item in invalid)
        )
    if not candidates:
        return [], notes

    _assert_no_package_collision(candidates)
    deduplicated: list[Candidate] = []
    seen: set[tuple] = set()
    for candidate in candidates:
        fingerprint = _candidate_fingerprint(candidate)
        if fingerprint not in seen:
            seen.add(fingerprint)
            deduplicated.append(candidate)
    return deduplicated, notes


def _candidate_fingerprint(item: Candidate) -> tuple:
    return (
        item.package_version,
        item.digest,
        json.dumps(item.base_identity, sort_keys=True),
        json.dumps(item.target_identity, sort_keys=True),
        str(item.manifest.get("payloadHash") or item.identity.get("payloadHash") or ""),
    )


def _assert_no_package_collision(candidates: list[Candidate]) -> None:
    by_version: dict[int, list[Candidate]] = {}
    for item in candidates:
        if item.package_version:
            by_version.setdefault(item.package_version, []).append(item)
    collisions: list[str] = []
    for version, values in sorted(by_version.items()):
        fingerprints = {_candidate_fingerprint(item) for item in values}
        if len(fingerprints) > 1:
            collisions.append(
                f"packageVersion={version}: "
                + ", ".join(sorted(item.path.name for item in values))
            )
    if collisions:
        raise UpdateError(
            "同一 project/packageVersion 存在不同 update 包，禁止猜测：\n"
            + "\n".join(f"- {item}" for item in collisions)
        )


def _compatible_candidates(root: Path, config: dict, package_arg: str | None = None) -> tuple[list[Candidate], list[str]]:
    project = config["project"]["id"]
    if package_arg:
        candidates = [_candidate_from_argument(package_arg)]
        notes: list[str] = []
    else:
        candidates, notes = _discover_next_candidates(root, config)
    compatible: list[Candidate] = []
    for item in candidates:
        if item.identity.get("packageType") != "update":
            continue
        if item.project != project:
            notes.append(f"其他项目：{item.path.name}: {item.project}")
            continue
        # Do not filter by projectVersion.  Business versions may legitimately
        # change inside an update package; contentHash is the compatibility
        # authority and packageVersion only provides ordering.
        compatible.append(item)
    _assert_no_package_collision(compatible)
    return compatible, notes


def _parse_package_version_from_name(value: object) -> int:
    text = str(value or "")
    match = re.search(r"-(\d{4,})(?:\.zip|$)", text)
    if not match:
        return 0
    return int(match.group(1))


def _baseline_package_version(root: Path) -> int:
    try:
        from script.project import flow_baseline

        state = flow_baseline.read_state(root) or {}
    except Exception:
        state = {}
    value = state.get("packageVersion") or 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 0
    if parsed:
        return parsed
    return max(
        _parse_package_version_from_name(state.get("lastAppliedPackage")),
        _parse_package_version_from_name(state.get("source")),
    )


def _select(root: Path, config: dict, package_arg: str | None = None) -> tuple[Candidate | None, list[str]]:
    compatible, current_notes = _compatible_candidates(root, config, package_arg)
    if not compatible:
        return None, current_notes
    if package_arg:
        return compatible[0], current_notes
    current_package_version = _baseline_package_version(root)
    current_by_scheme: dict[str, str] = {}
    applicable: list[Candidate] = []
    for item in compatible:
        if item.package_version and item.package_version <= current_package_version:
            continue
        scheme = item.base_identity["scheme"]
        if scheme not in current_by_scheme:
            current_by_scheme[scheme] = _identity_value(root, scheme, config)
        current = current_by_scheme[scheme]
        if current == item.base_identity["value"] or current == item.target_identity["value"]:
            applicable.append(item)
    if not applicable:
        higher = [item for item in compatible if not item.package_version or item.package_version > current_package_version]
        if higher:
            current_notes.append(
                f"发现 {len(higher)} 个更高序号更新，但没有 from.contentHash 接上当前内容身份"
            )
        return None, current_notes
    applicable.sort(key=lambda item: (item.package_version, _version_key(item.to_version), item.path.stat().st_mtime))
    same = [item for item in applicable if item.package_version == applicable[0].package_version and item.base_identity == applicable[0].base_identity]
    if len(same) > 1:
        raise UpdateError("同一 packageVersion/fromHash 存在多个候选，禁止猜测：\n" + "\n".join(f"- {item.path.name}" for item in same))
    return applicable[0], current_notes


def _manifest_paths(candidate: Candidate) -> list[str]:
    return [str(item["path"]) for item in candidate.manifest["files"]] + [str(item) for item in candidate.manifest["delete"]]


def _validate_targets(candidate: Candidate, config: dict) -> None:
    blocked = [
        relative
        for relative in _manifest_paths(candidate)
        if any(_matches(relative, pattern) for pattern in config["update"]["protected"])
    ]
    if blocked:
        raise UpdateError("更新包触及本机或不可覆盖范围：\n" + "\n".join(f"- {item}" for item in sorted(blocked)))


def _dirty_paths(root: Path) -> list[str]:
    raw = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "-z"], cwd=root, capture_output=True, check=True
    ).stdout
    paths: list[str] = []
    entries = [item for item in raw.split(b"\0") if item]
    index = 0
    while index < len(entries):
        entry = entries[index].decode("utf-8")
        status = entry[:2]
        path = entry[3:]
        if status[0] in {"R", "C"} and index + 1 < len(entries):
            index += 1
            path = entries[index].decode("utf-8")
        paths.append(path)
        index += 1
    return paths


def _is_protected(relative: str, config: dict) -> bool:
    return any(_matches(relative, pattern) for pattern in config["update"]["protected"])


def _project_dirty_paths(root: Path, config: dict, dirty: list[str] | None = None) -> list[str]:
    values = dirty if dirty is not None else _dirty_paths(root)
    return sorted({path for path in values if not _is_protected(path, config)})


def _git_paths(root: Path, *args: str) -> list[str]:
    completed = subprocess.run(
        ["git", *args, "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return [item.decode("utf-8") for item in completed.stdout.split(b"\0") if item]


def _current_project_paths(root: Path, config: dict) -> list[str]:
    values = _git_paths(root, "ls-files", "--cached", "--others", "--exclude-standard")
    return sorted({path for path in values if not _is_protected(path, config)})


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _overlay_current_project(root: Path, staging: Path, config: dict) -> None:
    """Make staging's project-owned view match the current working tree.

    Update identity is based on the current project-owned content, not on
    whether that content has already been committed.  This allows a verified
    update result from an older Flow version to be used as the next package
    baseline without forcing a manual bridge commit.
    """

    current_paths = set(_current_project_paths(root, config))
    tracked_paths = set(_git_paths(root, "ls-files", "--cached"))
    for relative in sorted(path for path in tracked_paths if not _is_protected(path, config)):
        if relative not in current_paths or not (root / relative).exists():
            _remove_path(staging / _safe_path(relative))
    for relative in sorted(current_paths):
        source = root / _safe_path(relative)
        target = staging / _safe_path(relative)
        if source.is_symlink():
            raise UpdateError(f"project-owned 基线不允许符号链接：{relative}")
        if source.is_dir():
            _remove_path(target)
            shutil.copytree(source, target)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_dir():
                shutil.rmtree(target)
            shutil.copy2(source, target)


def _stage_project_owned(root: Path, config: dict) -> list[str]:
    # Stage only the current project-owned dirty paths.  Do not stage the
    # entire project-owned inventory: after generated/local cleanup, that
    # inventory may still contain legacy tracked-data paths that are now
    # ignored by .gitignore, and git refuses to add ignored untracked paths
    # explicitly.  The update transaction only needs to commit actual changes
    # produced by the accepted candidate plus any already-verified project-owned
    # dirty base state.
    #
    # A deleted path needs special treatment. ``git add -A -- deleted-file``
    # works once, but the same pathspec is rejected after that deletion is
    # already staged because the path no longer exists in either the worktree
    # or index.  Update transactions stage before identity/baseline checks and
    # stage again while committing, so deletion staging must be idempotent.
    paths = _project_dirty_paths(root, config)
    existing = [relative for relative in paths if (root / relative).exists()]
    missing = [relative for relative in paths if not (root / relative).exists()]
    for start in range(0, len(existing), 200):
        subprocess.run(["git", "add", "-A", "--", *existing[start:start + 200]], cwd=root, check=True)
    for start in range(0, len(missing), 200):
        subprocess.run(
            ["git", "update-index", "--remove", "--", *missing[start:start + 200]],
            cwd=root,
            check=True,
        )

    # Protected/generated state must never leak into an automatic update
    # commit, even when it was staged before the update command started.
    return _unstage_protected(root, config)
def _unstage_protected(root: Path, config: dict) -> list[str]:
    staged = _git_paths(root, "diff", "--cached", "--name-only")
    protected_staged = sorted(path for path in staged if _is_protected(path, config))
    if protected_staged:
        for start in range(0, len(protected_staged), 200):
            subprocess.run(
                ["git", "reset", "-q", "HEAD", "--", *protected_staged[start:start + 200]],
                cwd=root,
                check=True,
            )
    return protected_staged


def _commit_message(candidate: Candidate, config: dict) -> str:
    template = str(
        config["update"].get(
            "commitMessageTemplate",
            "更新 {projectId} {fromVersion} → {toVersion}",
        )
    )
    return template.format(
        projectId=config["project"]["id"],
        fromVersion=candidate.from_version,
        toVersion=candidate.to_version,
    )


def _commit_project_owned(root: Path, message: str, config: dict) -> tuple[str, bool, list[str]]:
    protected_unstaged = _stage_project_owned(root, config)
    staged_diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=root,
        check=False,
    ).returncode
    if staged_diff not in {0, 1}:
        raise UpdateError("无法判断更新提交内容")
    created = staged_diff == 1
    if created:
        completed = subprocess.run(
            ["git", "commit", "--no-verify", "-m", message],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode:
            raise UpdateError((completed.stderr or completed.stdout or "Git 自动提交失败").strip())
    commit = _git(root, "rev-parse", "HEAD")
    remaining = _project_dirty_paths(root, config)
    if remaining:
        raise UpdateError(
            "自动提交后仍存在 project-owned 修改：\n"
            + "\n".join(f"- {item}" for item in remaining)
        )
    return commit, created, protected_unstaged


def _commit_update(root: Path, candidate: Candidate, config: dict) -> tuple[str, str, bool, list[str]]:
    message = _commit_message(candidate, config)
    commit, created, protected_unstaged = _commit_project_owned(root, message, config)
    return commit, message, created, protected_unstaged


def _extract(candidate: Candidate, target: Path, max_bytes: int) -> None:
    with zipfile.ZipFile(candidate.path) as archive:
        for item in candidate.manifest["files"]:
            relative = str(item["path"])
            member = archive.getinfo(f"payload/{relative}")
            if member.file_size > max_bytes:
                raise UpdateError(f"更新文件过大：{relative}")
            output = target / _safe_path(relative)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(archive.read(member))
            output.chmod(int(item.get("mode", 0o644)) & 0o777)
            if sha256_file(output) != str(item["sha256"]).lower():
                raise UpdateError(f"Payload 哈希不一致：{relative}")
        for relative in candidate.manifest["delete"]:
            path = target / _safe_path(str(relative))
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()


def _render(command: list[str], project: Path, trusted_root: Path) -> list[str]:
    rendered: list[str] = []
    for item in command:
        if item == "{python}":
            rendered.append(sys.executable)
        elif item == "{project-python}":
            raise UpdateError("候选验证器仍使用已退役的 {project-python}；请改用 uv runner")
        elif item == "{project}":
            rendered.append(str(project))
        else:
            rendered.append(item)
    return rendered


def _stage_and_validate(root: Path, candidate: Candidate, config: dict) -> None:
    with tempfile.TemporaryDirectory(prefix="spider-flow-update-stage-") as temp_name:
        staging = Path(temp_name) / "project"
        run(["git", "worktree", "add", "--detach", str(staging), "HEAD"], root, capture=True)
        try:
            _overlay_current_project(root, staging, config)
            local = root / ".flow/local.json"
            if local.is_file():
                (staging / ".flow").mkdir(parents=True, exist_ok=True)
                shutil.copy2(local, staging / ".flow/local.json")
            _extract(candidate, staging, int(config["update"]["maxFileBytes"]))
            version = (staging / config["project"]["versionFile"]).read_text("utf-8").strip()
            if version != candidate.to_version:
                raise UpdateError(f"Staging 版本 {version} != {candidate.to_version}")
            scheme = candidate.target_identity["scheme"]
            if scheme == "git-tree":
                run(["git", "add", "-A"], staging, capture=True)
                if local.is_file():
                    subprocess.run(["git", "reset", "-q", "--", ".flow/local.json"], cwd=staging, check=False, capture_output=True)
                actual_identity = _git(staging, "write-tree")
            else:
                actual_identity = _identity_value(staging, scheme, config)
            if actual_identity != candidate.target_identity["value"]:
                raise UpdateError(
                    f"Staging 内容身份不匹配：{actual_identity} != {candidate.target_identity['value']}"
                )
            env = os.environ.copy()
            env["FLOW_CANDIDATE_ROOT"] = str(staging)
            env["FLOW_PROJECT_ROOT"] = str(root)
            env["PYTHONPATH"] = str(staging)
            command = _render(config["update"]["candidateVerifier"], staging, root)
            run(command, staging, env=env, capture=True)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(staging)], cwd=root, check=False, capture_output=True)


def _backup_path(root: Path, transaction: Path, relative: str) -> dict:
    source = root / _safe_path(relative)
    record = {"path": relative, "existed": source.exists(), "kind": "missing"}
    if source.is_file():
        target = transaction / "backup/files" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        record.update({"kind": "file", "sha256": sha256_file(target)})
    elif source.is_dir():
        target = transaction / "backup/dirs" / relative
        shutil.copytree(source, target)
        record["kind"] = "dir"
    return record


def _prune_empty_parents(root: Path, start: Path) -> None:
    current = start
    while current != root and root in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _apply_to_root(root: Path, candidate: Candidate, transaction: Path, config: dict) -> list[dict]:
    records = [_backup_path(root, transaction, relative) for relative in _manifest_paths(candidate)]
    with tempfile.TemporaryDirectory(prefix="spider-flow-update-payload-") as temp_name:
        payload = Path(temp_name)
        _extract(candidate, payload, int(config["update"]["maxFileBytes"]))
        for item in candidate.manifest["files"]:
            relative = str(item["path"])
            source = payload / relative
            target = root / _safe_path(relative)
            if target.is_dir():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".flow-update.tmp")
            shutil.copy2(source, temporary)
            temporary.replace(target)
        for relative in candidate.manifest["delete"]:
            target = root / _safe_path(str(relative))
            parent = target.parent
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            _prune_empty_parents(root, parent)
    return records


def _restore(root: Path, transaction: Path, records: list[dict]) -> None:
    for record in records:
        target = root / _safe_path(record["path"])
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        if not record["existed"]:
            continue
        if record["kind"] == "file":
            source = transaction / "backup/files" / record["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        elif record["kind"] == "dir":
            shutil.copytree(transaction / "backup/dirs" / record["path"], target)


def _write_metadata(transaction: Path, payload: dict) -> None:
    transaction.mkdir(parents=True, exist_ok=True)
    temporary = transaction / "transaction.json.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(transaction / "transaction.json")


def _raw_sha256(value: object) -> str | None:
    text = str(value or "")
    if not text:
        return None
    return text.removeprefix("sha256:")


def _ensure_backup_record(root: Path, transaction: Path, records: list[dict], relative: str) -> None:
    if relative not in {str(item["path"]) for item in records}:
        records.append(_backup_path(root, transaction, relative))


def _should_write_flow_baseline(candidate: Candidate) -> bool:
    return candidate.target_identity.get("scheme") in {"flow-content-sha256", "project-owned-sha256"} or candidate.manifest.get("schemaVersion") == 2


def _write_flow_baseline(root: Path, candidate: Candidate, records: list[dict], transaction: Path) -> dict:
    from script.project import flow_baseline

    _ensure_backup_record(root, transaction, records, flow_baseline.BASELINE_PATH.as_posix())
    manifest = candidate.manifest
    target = manifest.get("to") if isinstance(manifest.get("to"), dict) else {}
    payload_digest = _raw_sha256(manifest.get("payloadHash"))
    if payload_digest is None:
        payload_digest = flow_baseline.payload_hash(manifest["files"], manifest["delete"])
    state = flow_baseline.build_state(
        root,
        version=candidate.to_version,
        package_sha256=candidate.digest,
        payload_sha256=payload_digest,
        quick_receipt_sha256=_raw_sha256(target.get("quickReceiptHash") or manifest.get("quickReceiptHash")),
        source=f"update:{candidate.path.name}",
    )
    if candidate.package_version:
        state["packageVersion"] = candidate.package_version
        state["lastAppliedPackage"] = candidate.path.name
    state["acceptedFrom"] = {
        "version": candidate.from_version,
        "contentIdentity": candidate.base_identity,
        "packageVersion": candidate.manifest.get("fromPackageVersion"),
    }
    state["target"] = {
        "version": candidate.to_version,
        "contentIdentity": candidate.target_identity,
        "packageVersion": candidate.package_version or None,
    }
    flow_baseline.write_state(root, state)
    return state


def _write_synced_flow_baseline(root: Path, candidate: Candidate, config: dict, *, reason: str) -> tuple[dict, str, bool]:
    from script.project import flow_baseline

    manifest = candidate.manifest
    target = manifest.get("to") if isinstance(manifest.get("to"), dict) else {}
    payload_digest = _raw_sha256(manifest.get("payloadHash"))
    if payload_digest is None:
        payload_digest = flow_baseline.payload_hash(manifest["files"], manifest["delete"])
    version = str(target.get("version") or candidate.to_version)
    try:
        state = flow_baseline.build_state(
            root,
            version=version,
            package_sha256=candidate.digest,
            payload_sha256=payload_digest,
            quick_receipt_sha256=_raw_sha256(target.get("quickReceiptHash") or manifest.get("quickReceiptHash")),
            source=f"package-sync:{candidate.path.name}",
        )
    except Exception:
        # Some legacy/minimal test fixtures do not have the full Spider path
        # profile needed to rebuild the file inventory.  Package sync should
        # still be able to repair the authoritative baseline identity when the
        # current content is already proven to equal a known target hash.
        state = {
            "schemaVersion": 1,
            "project": config["project"]["id"],
            "version": version,
            "baselineId": f"{version}@flow-content:{candidate.target_identity['value'][:12]}",
            "contentIdentity": candidate.target_identity,
            "contentHash": f"sha256:{candidate.target_identity['value']}",
            "artifactHash": f"sha256:{candidate.digest}",
            "payloadHash": f"sha256:{payload_digest}" if payload_digest else None,
            "source": f"package-sync:{candidate.path.name}",
            "excludedFromContentHash": [flow_baseline.BASELINE_PATH.as_posix()],
        }
    if candidate.package_version:
        state["packageVersion"] = candidate.package_version
        state["lastAppliedPackage"] = candidate.path.name
    state["syncReason"] = reason
    state["acceptedFrom"] = {
        "version": candidate.from_version,
        "contentIdentity": candidate.base_identity,
        "packageVersion": candidate.manifest.get("fromPackageVersion")
        or (candidate.manifest.get("from") or {}).get("packageVersion"),
    }
    state["target"] = {
        "version": candidate.to_version,
        "contentIdentity": candidate.target_identity,
        "packageVersion": candidate.package_version or None,
    }
    before = flow_baseline.baseline_path(root).read_text("utf-8") if flow_baseline.baseline_path(root).is_file() else ""
    flow_baseline.write_state(root, state)
    after = flow_baseline.baseline_path(root).read_text("utf-8")
    if before == after:
        return state, _git(root, "rev-parse", "HEAD"), False
    commit, created, _protected_unstaged = _commit_project_owned(
        root, f"同步 Flow baseline {candidate.package_version or candidate.to_version}", config
    )
    return state, commit, created


def _inspect_action(root: Path, config: dict, package_arg: str | None = None):
    candidate, notes = _select(root, config, package_arg)
    inbox, applied = _roots(root, config)
    completed = [f"更新根目录：{inbox}", f"归档目录：{applied}", *notes]
    if candidate is None:
        return _result("成功", "没有适用于当前项目和版本的更新", completed, [], "继续当前工作", "无需回滚")
    _validate_targets(candidate, config)
    current = _identity_value(root, candidate.base_identity["scheme"], config)
    if current == candidate.target_identity["value"]:
        return _result(
            "成功",
            f"已是目标内容身份：{candidate.to_version}",
            completed + [
                f"Artifact：{candidate.path.name}",
                f"SHA-256：{candidate.digest}",
                f"当前内容身份：{current[:12]}",
                f"目标内容身份：{candidate.target_identity['value'][:12]}",
                "该更新已应用，无需重复执行",
            ],
            [],
            "继续当前工作；如需刷新 WikiWiki source，请执行 ./flow wikiwiki --full",
            "无需回滚",
        )
    if current != candidate.base_identity["value"]:
        raise UpdateError(f"当前内容身份不匹配：{current} != {candidate.base_identity['value']}")
    return _result(
        "成功",
        f"可更新：{candidate.from_version} → {candidate.to_version}",
        completed + [f"Artifact：{candidate.path.name}", f"SHA-256：{candidate.digest}", f"变更路径：{len(_manifest_paths(candidate))}"],
        [],
        "./flow update --confirm",
        "应用失败会自动恢复",
    )


def _flow_result_data(value: dict, key: str) -> list[str]:
    data = value.get("data") if isinstance(value.get("data"), dict) else {}
    items = data.get(key) or []
    return [str(item) for item in items]


def _run_fresh_flow(root: Path, args: list[str], *, depth: int) -> dict:
    if depth > 100:
        raise UpdateError("自动更新链超过 100 个版本，拒绝继续")
    flow_entry = root / "flow"
    if not flow_entry.is_file():
        raise UpdateError("自动更新需要项目根目录 flow 启动器")
    env = os.environ.copy()
    env["FLOW_UPDATE_CHAIN_DEPTH"] = str(depth)
    command = [sys.executable, str(flow_entry), *args, "--json"]
    completed = subprocess.run(
        command,
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    output = (completed.stdout or "").strip()
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        detail = (completed.stderr or output or "新版 Flow 未返回 JSON 结果").strip()
        raise UpdateError(f"新版 Flow 返回无法解析：{detail}") from exc
    if completed.returncode or int(value.get("exitCode", 0)):
        detail = str(value.get("firstError") or value.get("message") or completed.stderr or "更新子进程失败")
        raise UpdateError(detail)
    return value


def _automatic_update_action(root: Path, args: list[str], config: dict):
    candidate, notes = _select(root, config, None)
    current_package_version = _baseline_package_version(root)
    if candidate is None:
        return _result(
            "成功",
            f"没有可应用更新；当前 packageVersion={current_package_version}",
            notes,
            [],
            "继续当前工作",
            "无需回滚",
        )
    _validate_targets(candidate, config)
    if "--yes" not in args:
        if "--non-interactive" in args:
            return _result(
                "等待确认",
                "自动更新尚未执行",
                notes,
                [f"待应用 packageVersion：{candidate.package_version}"],
                "./flow update --confirm",
                "无需回滚",
                40,
            )
        answer = input(
            f"将从 packageVersion {current_package_version} 开始自动顺序更新，"
            f"下一包为 {candidate.package_version}，是否继续？ [y/N] "
        ).strip().lower()
        if answer not in {"y", "yes"}:
            return _result(
                "取消",
                "原项目保持不变",
                [],
                ["未应用自动更新"],
                "重新执行 ./flow update",
                "无需回滚",
                130,
            )

    try:
        depth = int(os.getenv("FLOW_UPDATE_CHAIN_DEPTH", "0") or "0")
    except ValueError:
        depth = 0
    child = _run_fresh_flow(
        root,
        [
            "update",
            "--package",
            str(candidate.path),
            "--confirm",
            "--non-interactive",
        ],
        depth=depth,
    )
    # The applied package may replace Flow itself.  Never continue with the
    # current interpreter/module graph; reload the on-disk launcher in a fresh
    # process and let that version locate only its own exact N+1 package.
    continuation = _run_fresh_flow(
        root,
        ["update", "--confirm", "--non-interactive"],
        depth=depth + 1,
    )
    final_package_version = _baseline_package_version(root)
    completed = [
        *notes,
        f"自动应用 packageVersion {candidate.package_version}：{candidate.path.name}",
        f"子进程结果：{child.get('message', '成功')}",
        "已从磁盘重新启动更新后的 Flow",
    ]
    completed.extend(
        item for item in _flow_result_data(child, "completed")
        if item.startswith("更新提交") or item.startswith("package sync")
    )
    continuation_completed = _flow_result_data(continuation, "completed")
    completed.extend(continuation_completed)
    incomplete = sorted(set(
        _flow_result_data(child, "incomplete")
        + _flow_result_data(continuation, "incomplete")
    ))
    return _result(
        "成功",
        f"自动更新完成；当前 packageVersion={final_package_version}",
        completed,
        incomplete,
        str(continuation.get("nextAction") or "./flow run 或 ./flow push"),
        "./flow rollback",
    )


def _apply_action(root: Path, args: list[str], config: dict):
    removed_deprecated = remove_deprecated_local_dirs(root)
    required = config["update"]["requiredBranch"]
    branch = _git(root, "branch", "--show-current", check=False)
    auto_default = "--auto-default" in args
    if branch != required:
        if auto_default:
            return _result(
                "成功",
                f"自动更新跳过：当前分支 {branch or 'detached'}，要求 {required}",
                [],
                [],
                f"切换到 {required} 后重新执行 ./flow",
                "无需回滚",
            )
        raise UpdateError(f"当前分支 {branch or 'detached'}，要求 {required}")
    dirty = _dirty_paths(root)
    package_arg = None
    if "--package" in args:
        index = args.index("--package")
        package_arg = args[index + 1]
    if package_arg is None and _baseline_package_version(root) > 0:
        return _automatic_update_action(root, args, config)
    candidate, notes = _select(root, config, package_arg)
    if candidate is None:
        return _result("成功", "没有可应用更新", [*notes, *[f"已清理退役本地目录：{item}" for item in removed_deprecated]], [], "继续当前工作", "无需回滚")
    _validate_targets(candidate, config)
    current_identity = _identity_value(root, candidate.base_identity["scheme"], config)
    if current_identity == candidate.target_identity["value"]:
        sync_state, sync_commit, sync_created = _write_synced_flow_baseline(
            root, candidate, config, reason="idempotent-target-content"
        )
        completed = [
            *notes,
            f"Artifact：{candidate.path.name}",
            f"当前内容身份：{current_identity[:12]}",
            f"目标内容身份：{candidate.target_identity['value'][:12]}",
            "该更新已应用，未重复写入工作区",
            f"baseline.packageVersion：{sync_state.get('packageVersion', '?')}",
        ]
        if sync_created:
            completed.append(f"package sync 提交：{sync_commit[:12]}")
        return _result(
            "成功",
            f"已是目标内容身份：{candidate.to_version}",
            completed,
            [],
            "继续当前工作；如需刷新 WikiWiki source，请执行 ./flow wikiwiki --full",
            "无需回滚",
        )
    if current_identity != candidate.base_identity["value"]:
        unexplained = _project_dirty_paths(root, config, dirty)
        detail = ""
        if unexplained:
            detail = "\n当前 project-owned 修改：\n" + "\n".join(f"- {item}" for item in unexplained)
        raise UpdateError(
            f"当前内容身份不匹配：{current_identity} != {candidate.base_identity['value']}{detail}"
        )
    if "--yes" not in args:
        if "--non-interactive" in args:
            return _result("等待确认", "更新尚未执行", [], [f"待更新：{candidate.from_version} → {candidate.to_version}"], "./flow update --confirm", "无需回滚", 40)
        answer = input(f"将更新 {candidate.from_version} → {candidate.to_version}，是否继续？ [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            return _result("取消", "原项目保持不变", [], ["未应用更新"], "重新执行 ./flow update", "无需回滚", 130)
    _stage_and_validate(root, candidate, config)
    transaction = root / ".flow/state/transactions" / now_id()
    before = {
        "commit": _git(root, "rev-parse", "HEAD", check=False),
        "tree": _git(root, "rev-parse", "HEAD^{tree}", check=False),
        "version": (root / config["project"]["versionFile"]).read_text("utf-8").strip(),
        "protectedDirtyPaths": sorted(path for path in dirty if _is_protected(path, config)),
        "projectDirtyPaths": _project_dirty_paths(root, config, dirty),
    }
    records: list[dict] = []
    committed = False
    commit_hash = ""
    commit_message = ""
    commit_created = False
    protected_unstaged: list[str] = []
    archived_paths: list[Path] = []
    try:
        records = _apply_to_root(root, candidate, transaction, config)
        installed_version = (root / config["project"]["versionFile"]).read_text("utf-8").strip()
        if installed_version != candidate.to_version:
            raise UpdateError(
                f"应用后版本不匹配：{installed_version} != {candidate.to_version}"
            )
        # Stage the actual project-owned dirty set instead of the manifest path
        # list.  Delete entries in an update manifest may refer to paths that are
        # already absent in a rebased/local working tree; passing such paths
        # directly to ``git add`` can fail with a pathspec error before the
        # transaction can be committed.  Dirty-path staging also preserves the
        # generated/local protection rules used by normal update commits.
        protected_unstaged = _stage_project_owned(root, config)
        scheme = candidate.target_identity["scheme"]
        if scheme == "git-tree":
            actual_identity = _git(root, "write-tree")
        else:
            actual_identity = _identity_value(root, scheme, config)
        if actual_identity != candidate.target_identity["value"]:
            raise UpdateError(
                f"应用后内容身份不匹配：{actual_identity} != {candidate.target_identity['value']}"
            )
        flow_baseline_state = None
        if _should_write_flow_baseline(candidate):
            flow_baseline_state = _write_flow_baseline(root, candidate, records, transaction)
        commit_hash, commit_message, commit_created, additional_unstaged = _commit_update(
            root, candidate, config
        )
        protected_unstaged = sorted(set(protected_unstaged) | set(additional_unstaged))
        committed = commit_created
        _, applied = _roots(root, config)
        applied.mkdir(parents=True, exist_ok=True)
        destination = applied / candidate.path.name
        destination_sidecar = sidecar_path(destination)
        if destination.exists() or destination_sidecar.exists():
            suffix = candidate.digest[:12]
            destination = applied / f"{candidate.path.stem}-{suffix}{candidate.path.suffix}"
            destination_sidecar = sidecar_path(destination)
        shutil.copy2(candidate.path, destination)
        archived_paths.append(destination)
        moved_identity = dict(candidate.identity)
        moved_identity["artifactFile"] = destination.name
        destination_sidecar.write_text(json.dumps(moved_identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        archived_paths.append(destination_sidecar)
        metadata = {
            "schemaVersion": 1,
            "transactionId": transaction.name,
            "status": "applied",
            "rolledBack": False,
            "projectId": config["project"]["id"],
            "package": destination.name,
            "packageSha256": candidate.digest,
            "fromVersion": before["version"],
            "toVersion": candidate.to_version,
            "before": before,
            "targetIdentity": candidate.target_identity,
            "flowBaseline": flow_baseline_state,
            "commit": {
                "hash": commit_hash,
                "message": commit_message,
                "created": commit_created,
            },
            "protectedPathsUnstagedBeforeCommit": protected_unstaged,
            "paths": records,
            "archivedPackage": str(destination),
            "archivedSidecar": str(destination_sidecar),
        }
        _write_metadata(transaction, metadata)
        candidate.path.unlink(missing_ok=True)
        candidate.sidecar.unlink(missing_ok=True)
    except Exception:
        if committed and before["commit"]:
            subprocess.run(
                ["git", "reset", "--mixed", before["commit"]],
                cwd=root,
                check=False,
                capture_output=True,
            )
        if records:
            _restore(root, transaction, records)
            subprocess.run(
                ["git", "reset", "--mixed"],
                cwd=root,
                check=False,
                capture_output=True,
            )
        for path in archived_paths:
            path.unlink(missing_ok=True)
        raise
    completed = [
        *[f"已清理退役本地目录：{item}" for item in removed_deprecated],
        "候选离线控制面检查通过",
        "目标内容身份对账通过",
        "本机保护路径未被覆盖",
        f"更新提交：{commit_hash[:12]}",
        f"回滚点：{transaction.relative_to(root)}",
    ]
    if protected_unstaged:
        completed.append(f"受保护状态保持未提交：{len(protected_unstaged)} 个路径")
    return _result(
        "成功",
        f"已更新到 {candidate.to_version}，project-owned 代码已提交",
        completed,
        ["尚未推送；generated-state 仍独立管理"],
        "./flow run 或 ./flow push",
        "./flow rollback",
    )


def _latest_transaction(root: Path) -> tuple[Path, dict]:
    base = root / ".flow/state/transactions"
    for path in sorted(base.glob("*"), reverse=True):
        meta_path = path / "transaction.json"
        if not meta_path.is_file():
            continue
        meta = load_json(meta_path)
        if meta.get("status") == "applied" and not meta.get("rolledBack"):
            return path, meta
    raise UpdateError("没有可用的更新回滚点")


def _rollback_migration(root: Path, transaction: Path, meta: dict, config: dict):
    before_commit = str(meta.get("before", {}).get("commit", ""))
    if not before_commit:
        raise UpdateError("迁移回滚缺少原 Commit")
    download_root, _ = _roots(root, config)
    download_root.mkdir(parents=True, exist_ok=True)
    archive_base = download_root / f"{config['project']['id']}-migration-transaction-{transaction.name}"
    archive_path = Path(shutil.make_archive(str(archive_base), "zip", root_dir=transaction))

    # Reset tracked content first, then restore protected local changes and old
    # local control state captured by the migration installer.
    run(["git", "reset", "--hard", before_commit], root, capture=True)
    _restore(root, transaction, meta["paths"])

    flow_root = root / ".flow"
    if flow_root.exists():
        shutil.rmtree(flow_root)
    return _result(
        "成功",
        f"已回滚到 {meta['fromVersion']}，原 Git Commit 与本机状态已恢复",
        [
            f"Git 已恢复到 {before_commit[:12]}",
            "迁移前本机保护路径已恢复",
            f"事务材料已归档：{archive_path}",
        ],
        ["旧版控制面已恢复；当前新 Flow 已退出"],
        "重新运行迁移安装器可再次接入新公约",
        f"恢复包：{meta.get('recoveryPackage', '未记录')}",
    )


def _rollback_action(root: Path, args: list[str], config: dict):
    transaction, meta = _latest_transaction(root)
    allowed = {str(item["path"]) for item in meta["paths"]}
    unrelated = [
        path
        for path in _dirty_paths(root)
        if path not in allowed
        and not path.startswith(".flow/")
        and not any(_matches(path, pattern) for pattern in config["update"]["protected"])
    ]
    protected_before = set(meta.get("before", {}).get("protectedDirtyPaths", []))
    unrelated = [path for path in unrelated if path not in protected_before]
    if unrelated:
        raise UpdateError("存在与本次更新无关的工作区修改，拒绝回滚：\n" + "\n".join(f"- {item}" for item in unrelated))
    if "--yes" not in args:
        if "--non-interactive" in args:
            return _result("等待确认", "回滚尚未执行", [], [f"将回滚到 {meta['fromVersion']}"], "./flow rollback --confirm", "无需恢复", 40)
        answer = input(f"将从 {meta['toVersion']} 回滚到 {meta['fromVersion']}，是否继续？ [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            return _result("取消", "项目未变化", [], ["未回滚"], "重新执行 ./flow rollback", "无需恢复", 130)
    if meta.get("migration"):
        return _rollback_migration(root, transaction, meta, config)
    _restore(root, transaction, meta["paths"])
    rollback_message = (
        f"回滚 {config['project']['id']} {meta['toVersion']} → {meta['fromVersion']}"
    )
    rollback_commit, rollback_created, protected_unstaged = _commit_project_owned(
        root, rollback_message, config
    )
    meta["rolledBack"] = True
    meta["status"] = "rolled-back"
    meta["rollbackCommit"] = {
        "hash": rollback_commit,
        "message": rollback_message,
        "created": rollback_created,
    }
    meta["rollbackProtectedPathsUnstaged"] = protected_unstaged
    _write_metadata(transaction, meta)

    # Rollback may restore an older adapter/project-tool layout.  Never invoke
    # the current version's private post-switch command against the restored
    # tree.  The public ``flow status`` interface is the only cross-version
    # command that is safe here, and it is diagnostic rather than transactional.
    incomplete = ["尚未推送"]
    flow_entry = root / "flow"
    if flow_entry.is_file():
        completed = subprocess.run(
            [sys.executable, "flow", "status", "--json"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout or "旧版本 status 检查失败").strip()
            incomplete.append(f"旧版本状态检查未通过：{detail}")
    return _result(
        "成功",
        f"已回滚到 {meta['fromVersion']}，恢复内容已提交",
        [
            "旧版本文件已恢复",
            f"回滚提交：{rollback_commit[:12]}",
            "更新包仍保留在归档目录，可再次使用",
        ],
        incomplete,
        "可重新应用同一更新包，或按需推送回滚提交",
        f"事务材料：{transaction.relative_to(root)}",
    )


def execute(root: Path, action: str, args: list[str], config: dict):
    package_arg = None
    if "--package" in args:
        index = args.index("--package")
        if index + 1 >= len(args):
            raise UpdateError("--package 缺少路径")
        package_arg = args[index + 1]
    if action == "inspect":
        return _inspect_action(root, config, package_arg)
    if action == "apply":
        return _apply_action(root, args, config)
    if action == "rollback":
        return _rollback_action(root, args, config)
    raise UpdateError(f"未知 update.transaction 动作：{action}")
