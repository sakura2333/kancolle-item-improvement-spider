from __future__ import annotations

import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import hashlib

from script.project import flow_baseline
from script.project.command_support import result


class UpdatePackageError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _write_sidecar(
    artifact: Path,
    *,
    project_id: str,
    package_id: str,
    from_version: str,
    to_version: str,
    base_identity: dict,
    target_identity: dict,
    manifest: dict,
) -> Path:
    sidecar = artifact.with_name(artifact.name + ".flow.json")
    payload = {
        "schemaVersion": 2,
        "artifactFile": artifact.name,
        "packageType": "update",
        "packageId": package_id,
        "projectId": project_id,
        "sha256": _sha256_file(artifact),
        "baseVersion": from_version,
        "targetVersion": to_version,
        "baseIdentity": base_identity,
        "targetIdentity": target_identity,
        "from": manifest["from"],
        "to": manifest["to"],
        "payloadHash": manifest["payloadHash"],
    }
    sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sidecar


def _load_local(root: Path) -> dict[str, Any]:
    path = root / ".flow/local.json"
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise UpdatePackageError(".flow/local.json 根节点必须是对象")
    return value


def _output_path(root: Path, args: list[str], project_id: str, from_version: str, to_version: str) -> Path:
    if "--output" in args:
        index = args.index("--output")
        if index + 1 >= len(args):
            raise UpdatePackageError("--output 缺少目标 zip 路径")
        output = Path(args[index + 1]).expanduser()
        if not output.is_absolute():
            output = root / output
        return output.resolve()
    local = _load_local(root)
    output_root = Path(str(local.get("downloadRoot", "/Users/sakana/Downloads/GPT-Projects"))).expanduser()
    return (output_root / f"{project_id}-{from_version}-to-{to_version}-flow-content-update-{_now_id()}.zip").resolve()


def _run_quick_if_needed(root: Path, target_content_hash: str, target_lock_hash: str, args: list[str]) -> tuple[Path, dict, str]:
    receipt_path, receipt, receipt_hash = flow_baseline.latest_quick_receipt(root)
    if receipt is not None and flow_baseline.receipt_binds_current_content(root, receipt):
        return receipt_path or root / ".flow/state/checks/before.json", receipt, receipt_hash or ""
    if "--use-existing-receipt" in args:
        raise UpdatePackageError("现有 Quick Receipt 不绑定当前 target contentHash；请先执行 ./flow check --profile quick")
    completed = subprocess.run(
        ["./flow", "check", "--profile", "quick", "--json"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "quick check failed").strip()
        raise UpdatePackageError(f"Quick Check 未通过，不能生成 update package：{detail}")
    receipt_path, receipt, receipt_hash = flow_baseline.latest_quick_receipt(root)
    if receipt is None or not flow_baseline.receipt_binds_current_content(root, receipt):
        raise UpdatePackageError(
            "Quick Receipt 未绑定当前 target contentHash："
            f"target={target_content_hash} lock={target_lock_hash}"
        )
    return receipt_path or root / ".flow/state/checks/before.json", receipt, receipt_hash or ""


def _diff_files(baseline_files: list[dict[str, Any]], target_files: list[flow_baseline.FileRecord]) -> tuple[list[dict[str, Any]], list[str]]:
    baseline_by_path = {str(item["path"]): item for item in baseline_files}
    target_by_path = {item.path: item for item in target_files}
    changed: list[dict[str, Any]] = []
    for relative, item in sorted(target_by_path.items()):
        previous = baseline_by_path.get(relative)
        if previous is None or previous.get("sha256") != item.sha256 or previous.get("mode") != item.mode:
            changed.append({"path": relative, "sha256": item.sha256, "mode": int(item.mode, 8), "sizeBytes": item.sizeBytes})
    delete = sorted(set(baseline_by_path) - set(target_by_path))
    return changed, delete


def run(root: Path, args: list[str], config: dict, loader=None) -> dict:
    project_id = config["project"]["id"]
    baseline = flow_baseline.read_state(root)
    if baseline is None:
        raise UpdatePackageError("缺少 .flow/baseline.json；请先应用 baseline update 后再生成业务更新包")
    baseline_hash = str(baseline.get("contentHash") or "").removeprefix("sha256:")
    if not baseline_hash:
        raise UpdatePackageError("Flow baseline 缺少 contentHash")
    current_version = (root / config["project"]["versionFile"]).read_text(encoding="utf-8").strip()
    from_version = str(baseline.get("version") or current_version)
    target_files = flow_baseline.content_files(root)
    target_hash = flow_baseline.hash_file_records(target_files)
    target_lock_hash = flow_baseline.lock_hash(root)
    if target_hash == baseline_hash:
        raise UpdatePackageError("当前内容等于 Flow baseline，没有需要打包的 project-owned 变化")
    changed, delete = _diff_files(list(baseline.get("files") or []), target_files)
    if not changed and not delete:
        raise UpdatePackageError("内容 Hash 变化但文件清单无差异，请检查 baseline 文件清单")
    receipt_path, receipt, receipt_hash = _run_quick_if_needed(root, target_hash, target_lock_hash, args)
    payload_hash = flow_baseline.payload_hash(changed, delete)
    output = _output_path(root, args, project_id, from_version, current_version)
    if output.suffix.lower() != ".zip":
        raise UpdatePackageError("update package 输出必须是 .zip")
    output.parent.mkdir(parents=True, exist_ok=True)
    base_identity = {"scheme": flow_baseline.CONTENT_SCHEME, "value": baseline_hash}
    target_identity = {"scheme": flow_baseline.CONTENT_SCHEME, "value": target_hash}
    manifest = {
        "schemaVersion": 2,
        "packageType": "update",
        "projectId": project_id,
        "fromVersion": from_version,
        "toVersion": current_version,
        "baseIdentity": base_identity,
        "targetIdentity": target_identity,
        "from": {
            "version": from_version,
            "contentHash": f"sha256:{baseline_hash}",
            "lockHash": baseline.get("lockHash"),
            "baselineId": baseline.get("baselineId"),
        },
        "to": {
            "version": current_version,
            "contentHash": f"sha256:{target_hash}",
            "lockHash": f"sha256:{target_lock_hash}",
            "quickReceiptHash": f"sha256:{receipt_hash}",
        },
        "payloadHash": f"sha256:{payload_hash}",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "files": changed,
        "delete": delete,
    }
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("update-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        archive.writestr("quick-receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        for item in changed:
            archive.write(root / item["path"], f"payload/{item['path']}")
    sidecar = _write_sidecar(
        output,
        project_id=project_id,
        package_id=f"{project_id}-flow-content-update-{_now_id()}",
        from_version=from_version,
        to_version=current_version,
        base_identity=base_identity,
        target_identity=target_identity,
        manifest=manifest,
    )
    return result(
        "成功",
        f"Flow content update package 已生成：{output}",
        [
            f"from.contentHash：{baseline_hash[:12]}",
            f"to.contentHash：{target_hash[:12]}",
            f"payloadHash：{payload_hash[:12]}",
            f"Quick Receipt：{receipt_path.relative_to(root).as_posix()}",
            f"Sidecar：{sidecar.name}",
            f"变更文件：{len(changed)}，删除：{len(delete)}",
            f"ZIP SHA-256：{_sha256_file(output)}",
        ],
        [],
        f"./flow update --package {output} --confirm",
        "该包不携带 .git；失败按 update.transaction 回滚",
    )
