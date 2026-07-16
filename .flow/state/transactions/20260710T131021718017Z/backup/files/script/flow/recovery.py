from __future__ import annotations

import fnmatch
import json
import shutil
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .artifact import write_sidecar
from .common import expand, load_json, now_id, sha256_file


class RecoveryError(RuntimeError):
    pass


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
    cp = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    if check and cp.returncode:
        raise RecoveryError((cp.stderr or cp.stdout or "Git 命令失败").strip())
    return (cp.stdout or "").strip()


def _excluded(relative: str, patterns: list[str]) -> bool:
    value = relative.replace("\\", "/")
    return any(
        value == pattern.rstrip("/")
        or value.startswith(pattern.rstrip("/") + "/")
        or fnmatch.fnmatch(value, pattern)
        for pattern in patterns
    )



def _excluded_from_explicit_root(relative: str, configured: str, patterns: list[str]) -> bool:
    configured_value = configured.replace("\\", "/").strip("/")
    effective: list[str] = []
    for pattern in patterns:
        normalized = pattern.replace("\\", "/").strip("/")
        if not any(token in normalized for token in "*?["):
            base = normalized.rstrip("/")
            if configured_value == base or configured_value.startswith(base + "/"):
                continue
        effective.append(pattern)
    return _excluded(relative, effective)

def _local(root: Path) -> dict:
    path = root / ".flow/local.json"
    return load_json(path) if path.is_file() else {}


def _output_root(root: Path, config: dict) -> Path:
    local = _local(root)
    value = local.get("recoveryOutputRoot") or local.get("downloadRoot") or "/Users/sakana/Downloads/GPT-Projects"
    return expand(str(value), root).resolve()


def _output_path(root: Path, args: list[str], config: dict, project: str, version: str, stamp: str) -> Path:
    if "--output" in args:
        index = args.index("--output")
        if index + 1 >= len(args):
            raise RecoveryError("--output 缺少完整目标文件路径")
        output = Path(args[index + 1]).expanduser()
        if not output.is_absolute():
            output = (root / output).resolve()
        else:
            output = output.resolve()
        if output.suffix.lower() != ".zip":
            raise RecoveryError("Recovery Artifact 必须使用 .zip 文件路径")
        return output
    return _output_root(root, config) / f"{project}-recovery-{version}-{stamp}.zip"


def _repository_files(root: Path) -> list[str]:
    raw = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    return sorted({item.decode("utf-8") for item in raw.split(b"\0") if item})


def _under(relative: str, roots: list[str]) -> bool:
    value = relative.replace("\\", "/").strip("/")
    return any(
        value == root.replace("\\", "/").strip("/")
        or value.startswith(root.replace("\\", "/").strip("/") + "/")
        for root in roots
    )


def _collect(root: Path, config: dict) -> dict[str, tuple[Path, str]]:
    result: dict[str, tuple[Path, str]] = {}
    recovery = config["recovery"]
    excludes = list(recovery["exclude"])
    generated_roots = [str(value) for value in recovery.get("includeGeneratedState", [])]
    local_roots = [str(value) for value in recovery.get("includeLocal", [])]

    for relative in _repository_files(root):
        source = root / relative
        if not source.is_file() or source.is_symlink() or _excluded(relative, excludes):
            continue
        if _under(relative, generated_roots):
            result[f"private/generated-state/{relative}"] = (source, "generated-state")
        elif _under(relative, local_roots):
            result[f"private/{relative}"] = (source, "local")
        else:
            result[f"project/{relative}"] = (source, "project-owned")

    def collect_private(configured: str, *, prefix: str, kind: str) -> None:
        source = root / configured
        if not source.exists():
            return
        paths = [source] if source.is_file() else source.rglob("*")
        for path in paths:
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            if _excluded_from_explicit_root(relative, configured, excludes):
                continue
            result[f"{prefix}/{relative}"] = (path, kind)

    for configured in recovery.get("includeLocal", []):
        collect_private(str(configured), prefix="private", kind="local")
    for configured in generated_roots:
        collect_private(
            configured, prefix="private/generated-state", kind="generated-state"
        )
    return result


def _build_handoff(root: Path, config: dict, manifest: dict) -> str:
    version = (root / config["project"]["versionFile"]).read_text("utf-8").strip()
    return f"""# GPT / 开发恢复入口

项目：`{config['project']['id']}`
版本：`{version}`
Commit：`{manifest['git']['commit']}`
Tree：`{manifest['git']['tree']}`

恢复顺序：

1. 校验 `recovery-manifest.json` 中所有文件 SHA-256；
2. 优先使用 `git/project.bundle` 恢复 Git 历史；
3. 将 `project/` 作为仅含 project-owned 文件的源码快照；
4. 将 `private/generated-state/` 与其他 `private/` 资料按需恢复，禁止直接发布；
5. 阅读 `project/SPIDER-HARD-RULES.md`、`project/SPIDER-AUTHORITY-MAP.md` 与 `project/docs/internal/DOCUMENTATION-MAP.md`；
6. 执行 `./flow status` 与 `./flow check --profile full`。

该恢复包同时承担开发恢复、迁移、GPT 交接和技术留档，不代表 Stable 发布候选。
"""


def _verify_zip(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if names.count("recovery-manifest.json") != 1:
                raise RecoveryError("恢复包缺少唯一 recovery-manifest.json")
            manifest = json.loads(archive.read("recovery-manifest.json").decode("utf-8"))
            if not isinstance(manifest, dict):
                raise RecoveryError("恢复 Manifest 无效")
            for item in manifest.get("files", []):
                member = str(item["path"])
                if names.count(member) != 1:
                    raise RecoveryError(f"恢复文件缺失或重复：{member}")
                import hashlib
                digest = hashlib.sha256(archive.read(member)).hexdigest()
                if digest != item["sha256"]:
                    raise RecoveryError(f"恢复文件哈希不一致：{member}")
    except zipfile.BadZipFile as exc:
        raise RecoveryError("不是有效 ZIP") from exc
    return manifest


def _write_file(archive: zipfile.ZipFile, source: Path, member: str) -> None:
    stat = source.stat()
    local = time.gmtime(max(stat.st_mtime, 315532800))
    info = zipfile.ZipInfo(member, date_time=local[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.st_mode & 0xFFFF) << 16
    archive.writestr(info, source.read_bytes())


def _atomic_replace(source: Path, target: Path) -> None:
    source.replace(target)


def _create(root: Path, args: list[str], config: dict):
    project = config["project"]["id"]
    version = (root / config["project"]["versionFile"]).read_text("utf-8").strip()
    commit = _git(root, "rev-parse", "HEAD", check=False)
    tree = _git(root, "rev-parse", "HEAD^{tree}", check=False)
    branch = _git(root, "branch", "--show-current", check=False)
    files = _collect(root, config)
    stamp = now_id()
    output = _output_path(root, args, config, project, version, stamp)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".spider-recovery-", dir=output.parent) as temp_name:
        temp = Path(temp_name)
        temporary_output = temp / output.name
        bundle = temp / "project.bundle"
        bundle_ok = False
        if commit:
            cp = subprocess.run(["git", "bundle", "create", str(bundle), "--all"], cwd=root, text=True, capture_output=True, check=False)
            bundle_ok = cp.returncode == 0 and bundle.is_file()
        manifest = {
            "schemaVersion": 1,
            "project": project,
            "version": version,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "git": {"commit": commit, "tree": tree, "branch": branch, "bundle": bundle_ok},
            "capabilities": config["capabilities"],
            "files": [],
            "privateContent": any(kind in {"local", "generated-state"} for _, kind in files.values()),
        }
        with zipfile.ZipFile(temporary_output, "w", zipfile.ZIP_DEFLATED) as archive:
            for member, (source, kind) in sorted(files.items()):
                _write_file(archive, source, member)
                manifest["files"].append({
                    "path": member,
                    "sha256": sha256_file(source),
                    "sizeBytes": source.stat().st_size,
                    "kind": kind,
                })
            if bundle_ok:
                _write_file(archive, bundle, "git/project.bundle")
                manifest["files"].append({
                    "path": "git/project.bundle",
                    "sha256": sha256_file(bundle),
                    "sizeBytes": bundle.stat().st_size,
                    "kind": "git-bundle",
                })
            handoff = _build_handoff(root, config, manifest).encode("utf-8")
            import hashlib
            archive.writestr("GPT-HANDOFF.md", handoff)
            manifest["files"].append({
                "path": "GPT-HANDOFF.md",
                "sha256": hashlib.sha256(handoff).hexdigest(),
                "sizeBytes": len(handoff),
                "kind": "handoff",
            })
            archive.writestr("recovery-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        verified = _verify_zip(temporary_output)
        _atomic_replace(temporary_output, output)
    sidecar = write_sidecar(
        output,
        package_type="recovery",
        package_id=f"{project}-recovery-{version}-{stamp}",
        project_id=project,
        version=version,
    )
    return _result(
        "成功",
        f"完整恢复包已生成：{output}",
        [f"文件数：{len(verified['files'])}", f"ZIP SHA-256：{sha256_file(output)}", f"Sidecar：{sidecar.name}", f"Git bundle：{'已包含' if verified['git']['bundle'] else '未包含'}"],
        ["恢复包包含 private/ 时仅限私有保存，不得发布"],
        "将恢复包保存到独立存储",
        "使用包内 GPT-HANDOFF.md 与 recovery-manifest.json 恢复",
    )


def execute(root: Path, action: str, args: list[str], config: dict):
    if action == "create":
        return _create(root, args, config)
    raise RecoveryError(f"未知 recovery.package 动作：{action}")
