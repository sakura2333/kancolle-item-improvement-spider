#!/usr/bin/env python3
from __future__ import annotations

"""Low-frequency, project-specific collaboration around Stable ``main``.

This tool deliberately sits outside the public Flow command protocol.  It
prepares a temporary public branch, lets an AI and a human review that branch,
and opens a one-shot gate only for the exact reviewed commit.  ``./flow
stable --confirm`` later consumes the gate; it never creates or merges the
branch itself.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from script.project import stable_command
from script.project.command_support import git, local_config
from script.project.main_release_gate import (
    MainReleaseGateError,
    gate_path,
    load_gate,
    mark_stale,
    open_gate,
)
from script.project.public_candidate_check import PublicCandidateError, inspect_candidate
from script.project.public_content_audit import inspect_public_text
from script.project.runtime import load as load_runtime


class MainReleaseError(RuntimeError):
    pass


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if completed.returncode:
        raise MainReleaseError((completed.stderr or completed.stdout or "命令失败").strip())
    return completed


def _write_manifest(state_root: Path, manifest: dict[str, Any]) -> Path:
    path = state_root / "candidate-manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def _write_beta_review_bundle(state_root: Path) -> tuple[Path, str]:
    candidate_archive = state_root / "candidate.zip"
    if not candidate_archive.is_file():
        stable_command._write_candidate_archive(state_root / "candidate", candidate_archive)
    entries = {
        "candidate.zip": candidate_archive,
        "beta-receipt.json": state_root / "beta-receipt.json",
        "beta-review-inventory.json": state_root / "beta-review-inventory.json",
        "candidate-manifest.json": state_root / "candidate-manifest.json",
        "public-content-audit.json": state_root / "public-content-audit.json",
    }
    exception_path = PROJECT_ROOT / "release/public-exceptions.json"
    if exception_path.is_file():
        entries["public-exceptions.json"] = exception_path
    missing = [name for name, path in entries.items() if not path.is_file()]
    if missing:
        raise MainReleaseError(f"Beta AI review bundle missing inputs: {missing}")
    forbidden = [str(PROJECT_ROOT.resolve()), "/Users/", "workspaceRoot", "downloadRoot"]
    for name, path in entries.items():
        if path.suffix not in {".json", ".txt", ".md"}:
            continue
        text = path.read_text(encoding="utf-8")
        hits = [token for token in forbidden if token in text]
        if hits:
            raise MainReleaseError(f"Beta AI review metadata contains local path data: {name}: {hits}")
    output = state_root / "beta-ai-review.zip"
    temporary = output.with_suffix(output.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o644 & 0xFFFF) << 16
            archive.writestr(info, path.read_bytes())
    temporary.replace(output)
    return output, stable_command._sha256(output)


def _stable_remote(config: dict) -> tuple[str, str]:
    stable = config["git"]["stable"]
    local = local_config(PROJECT_ROOT)
    push_target = local.get("git", {}).get("stable", {}).get("pushUrl", "") or stable["remote"]
    return stable["remote"], push_target


def _branch_name(config: dict, release_id: str) -> str:
    prefix = str(config["stable"].get("candidateBranchPrefix", "public-candidate/"))
    return prefix + release_id


def _beta_branch_name(config: dict, release_id: str) -> str:
    prefix = str(config["stable"].get("betaCandidateBranchPrefix", "public-beta/"))
    return prefix + release_id


def _remote_sha(target: str, branch: str, cwd: Path) -> str:
    completed = _run(["git", "ls-remote", target, f"refs/heads/{branch}"], cwd)
    line = completed.stdout.strip()
    return line.split()[0] if line else ""


def _write_review_delta(
    state_root: Path,
    config: dict,
    *,
    base_ref: str,
    candidate_commit: str,
) -> Path:
    completed = _run(
        ["git", "diff", "--name-status", "-M", base_ref, candidate_commit],
        PROJECT_ROOT,
    )
    categories = config["stable"].get("categories", {})
    changes: list[dict[str, Any]] = []
    counts = {name: 0 for name in categories}
    counts["uncategorized"] = 0
    for raw in completed.stdout.splitlines():
        parts = raw.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        path = parts[-1]
        category = next(
            (
                name
                for name, patterns in categories.items()
                if any(stable_command._matches(path, pattern) for pattern in patterns)
            ),
            "uncategorized",
        )
        counts[category] += 1
        changes.append({"status": status, "path": path, "category": category})
    if counts["uncategorized"]:
        raise MainReleaseError("公开候选包含未分类文件；检查 release/public-content.json")
    path = state_root / "main-review-delta.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "baseRef": base_ref,
                "candidateCommit": candidate_commit,
                "counts": counts,
                "changes": changes,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _review_template(state_root: Path, branch: str, commit: str, review_delta: Path | None = None) -> Path:
    path = state_root / "ai-review-template.json"
    value = {
        "schemaVersion": 1,
        "result": "approved",
        "candidateBranch": branch,
        "candidateCommit": commit,
        "reviewedAreas": [
            "public structure",
            "documentation consistency",
            "private or local information",
            "README/schema/export consistency",
            "public automation and workflow boundary",
        ],
        "blockingIssues": [],
        "reviewDelta": str(review_delta) if review_delta else None,
        "notes": "Review only the categorized public delta, then replace this note with the AI review summary. Commit any cleanup before approving.",
    }
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path



def _write_beta_inventory(
    state_root: Path,
    config: dict,
    candidate: Path,
    public_text_audit: dict[str, Any],
) -> Path:
    categories = config["stable"].get("categories", {})
    counts = {name: 0 for name in categories}
    counts["uncategorized"] = 0
    files: list[dict[str, str]] = []
    for source in sorted(candidate.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(candidate).as_posix()
        category = next(
            (
                name
                for name, patterns in categories.items()
                if any(stable_command._matches(relative, pattern) for pattern in patterns)
            ),
            "uncategorized",
        )
        counts[category] += 1
        files.append({"path": relative, "category": category})
    if counts["uncategorized"]:
        raise MainReleaseError("Beta 公开快照包含未分类文件；检查 release/public-content.json")
    path = state_root / "beta-review-inventory.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "counts": counts,
                "files": files,
                "publicIsolation": public_text_audit.get("publicIsolation"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _reset_worktree_to_candidate_snapshot(worktree: Path, candidate: Path) -> None:
    # Beta is an isolated, complete public snapshot.  It replaces the branch worktree with the exact shared Public Snapshot.
    # Beta and Stable therefore test the same file boundary and tree content.
    _run(["git", "rm", "-r", "-q", "--ignore-unmatch", "."], worktree)
    for untracked in worktree.iterdir():
        if untracked.name == ".git":
            continue
        if untracked.is_dir() and not untracked.is_symlink():
            shutil.rmtree(untracked)
        else:
            untracked.unlink()
    stable_command._copy_candidate(candidate, worktree)


def _write_beta_receipt(
    state_root: Path,
    manifest: dict[str, Any],
    *,
    branch: str,
    commit: str,
    tree: str,
    remote: str,
    public_text_audit: dict[str, Any],
) -> Path:
    content_manifest = state_root / "candidate" / "PUBLIC-CONTENT-MANIFEST.json"
    payload = {
        "schemaVersion": 3,
        "channel": "beta",
        "project": manifest["project"],
        "version": manifest["version"],
        "releaseId": manifest["releaseId"],
        "sourceCommit": manifest["sourceCommit"],
        "sourceTree": manifest["sourceTree"],
        "candidateSha256": manifest["candidateSha256"],
        "candidateContentSha256": manifest.get("candidateContentSha256", manifest["candidateSha256"]),
        "candidateArchiveSha256": manifest.get("candidateArchiveSha256"),
        "candidateArchive": "candidate.zip",
        "contentManifestSha256": stable_command._sha256(content_manifest),
        "publicTextAudit": public_text_audit,
        "publicIsolation": public_text_audit.get("publicIsolation"),
        "branch": branch,
        "commit": commit,
        "tree": tree,
        "remote": remote,
        "policy": "shared-whitelist-public-snapshot",
        "formalVersionChanged": False,
        "mainChanged": False,
        "npmPublished": False,
        "onlinePublished": False,
    }
    path = state_root / "beta-receipt.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path



def _verify_dev_pushed(config: dict) -> str:
    development = config["git"]["development"]
    remote = str(development["remote"])
    branch = str(development["branch"])
    _run(["git", "fetch", remote, branch], PROJECT_ROOT)
    local_head = git(PROJECT_ROOT, "rev-parse", "HEAD")
    remote_head = git(PROJECT_ROOT, "rev-parse", f"{remote}/{branch}")
    if local_head != remote_head:
        raise MainReleaseError(
            f"dev 尚未推送或远端已变化：local={local_head[:12]} remote={remote_head[:12]}；"
            f"先执行 git push {remote} {branch}"
        )
    return local_head


def prepare_beta(*, confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise MainReleaseError("创建并推送隔离 Beta 公开快照需要 --confirm")
    config = load_runtime()
    _verify_dev_pushed(config)
    latest = PROJECT_ROOT / config["stable"]["previewRoot"] / "latest.json"
    if latest.is_file():
        try:
            state_root, manifest = stable_command._load_latest(PROJECT_ROOT, config)
        except stable_command.StablePreviewStaleError:
            state_root, manifest = stable_command._preview(PROJECT_ROOT, config)
    else:
        state_root, manifest = stable_command._preview(PROJECT_ROOT, config)

    candidate = state_root / "candidate"
    public_text_audit = inspect_public_text(candidate, config["stable"])
    audit_path = state_root / "public-content-audit.json"
    if not audit_path.is_file():
        audit_path.write_text(json.dumps(public_text_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    candidate_sha256 = manifest["candidateSha256"]
    candidate_archive = state_root / "candidate.zip"
    archive_sha256 = manifest.get("candidateArchiveSha256")
    if not archive_sha256 or not candidate_archive.is_file():
        archive_sha256 = stable_command._write_candidate_archive(candidate, candidate_archive)
        manifest["schemaVersion"] = max(int(manifest.get("schemaVersion", 0)), 7)
        manifest["candidateContentSha256"] = manifest.get("candidateContentSha256", candidate_sha256)
        manifest["candidateArchiveSha256"] = archive_sha256
        manifest["candidateArchivePath"] = "candidate.zip"
        _write_manifest(state_root, manifest)
    remote_name, push_target = _stable_remote(config)
    branch = _beta_branch_name(config, manifest["releaseId"])
    recorded = manifest.get("betaBranch")
    if isinstance(recorded, dict) and recorded.get("name") == branch:
        existing = _remote_sha(push_target, branch, PROJECT_ROOT)
        if not existing:
            raise MainReleaseError(f"已记录的 Beta 分支在远端不存在：{branch}")
        if existing != recorded.get("preparedCommit"):
            raise MainReleaseError("Beta 分支 Commit 与本地 Receipt 不一致；拒绝自动覆盖")
        if recorded.get("candidateSha256") != candidate_sha256:
            raise MainReleaseError("Beta 分支绑定的公开快照已变化；必须生成新的 releaseId")
        receipt = state_root / "beta-receipt.json"
        inventory = state_root / "beta-review-inventory.json"
        bundle, bundle_hash = _write_beta_review_bundle(state_root)
        return {
            "status": "already-prepared",
            "channel": "beta",
            "releaseId": manifest["releaseId"],
            "branch": branch,
            "commit": existing,
            "tree": recorded.get("preparedTree"),
            "candidateContentSha256": manifest.get("candidateContentSha256", manifest["candidateSha256"]),
            "candidateArchiveSha256": manifest.get("candidateArchiveSha256"),
            "receipt": _relative(receipt),
            "reviewInventory": _relative(inventory),
            "reviewBundle": _relative(bundle),
            "reviewBundleSha256": bundle_hash,
        }

    existing = _remote_sha(push_target, branch, PROJECT_ROOT)
    if existing:
        raise MainReleaseError(
            f"远端已存在未被当前 Preview 记录的 Beta 分支：{branch}@{existing[:12]}；"
            "Beta 分支不可覆盖"
        )

    stable = config["git"]["stable"]
    _run(["git", "fetch", stable["remote"], stable["branch"]], PROJECT_ROOT)
    base_ref = f"{stable['remote']}/{stable['branch']}"
    with tempfile.TemporaryDirectory(prefix="spider-public-beta-") as temp_name:
        worktree = Path(temp_name) / "worktree"
        _run(["git", "worktree", "add", "--detach", str(worktree), base_ref], PROJECT_ROOT)
        try:
            _reset_worktree_to_candidate_snapshot(worktree, candidate)
            _run(["git", "add", "-A"], worktree)
            diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree, check=False)
            if diff.returncode == 0:
                commit = git(PROJECT_ROOT, "rev-parse", base_ref)
            else:
                _run(["git", "commit", "-m", f"准备 Spider {manifest['version']} Beta 公开快照"], worktree)
                commit = _run(["git", "rev-parse", "HEAD"], worktree).stdout.strip()
            tree = _run(["git", "rev-parse", "HEAD^{tree}"], worktree).stdout.strip()
            _run(["git", "push", push_target, f"HEAD:refs/heads/{branch}"], worktree)
            if _remote_sha(push_target, branch, worktree) != commit:
                raise MainReleaseError("Beta 公开快照远端回读 Commit 不一致")
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

    inventory = _write_beta_inventory(state_root, config, candidate, public_text_audit)
    receipt = _write_beta_receipt(
        state_root,
        manifest,
        branch=branch,
        commit=commit,
        tree=tree,
        remote=remote_name,
        public_text_audit=public_text_audit,
    )
    manifest["betaBranch"] = {
        "name": branch,
        "remote": remote_name,
        "preparedCommit": commit,
        "preparedTree": tree,
        "candidateSha256": candidate_sha256,
        "candidateContentSha256": manifest.get("candidateContentSha256", candidate_sha256),
        "candidateArchiveSha256": manifest.get("candidateArchiveSha256"),
        "policy": "shared-whitelist-public-snapshot",
    }
    _write_manifest(state_root, manifest)
    bundle, bundle_hash = _write_beta_review_bundle(state_root)
    return {
        "status": "prepared",
        "channel": "beta",
        "releaseId": manifest["releaseId"],
        "branch": branch,
        "commit": commit,
        "tree": tree,
        "candidateSha256": candidate_sha256,
        "candidateContentSha256": manifest.get("candidateContentSha256", candidate_sha256),
        "candidateArchiveSha256": manifest.get("candidateArchiveSha256"),
        "receipt": _relative(receipt),
        "reviewInventory": _relative(inventory),
        "reviewBundle": _relative(bundle),
        "reviewBundleSha256": bundle_hash,
        "next": "AI-review the exact reviewBundle, then test this immutable Beta branch",
    }


def prepare(*, confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise MainReleaseError("创建并推送临时公开候选分支需要 --confirm")
    config = load_runtime()
    _verify_dev_pushed(config)
    latest = PROJECT_ROOT / config["stable"]["previewRoot"] / "latest.json"
    if latest.is_file():
        try:
            state_root, manifest = stable_command._load_latest(
                PROJECT_ROOT, config
            )
        except stable_command.StablePreviewStaleError:
            state_root, manifest = stable_command._preview(
                PROJECT_ROOT, config
            )
    else:
        state_root, manifest = stable_command._preview(PROJECT_ROOT, config)
    remote, push_target = _stable_remote(config)
    stable = config["git"]["stable"]
    recorded = manifest.get("reviewBranch")
    if isinstance(recorded, dict) and recorded.get("name"):
        branch = str(recorded["name"])
        existing = _remote_sha(push_target, branch, PROJECT_ROOT)
        if not existing:
            raise MainReleaseError(f"已记录的临时分支在远端不存在：{branch}")
        stable = config["git"]["stable"]
        _run(["git", "fetch", stable["remote"], stable["branch"]], PROJECT_ROOT)
        base_ref = f"{stable['remote']}/{stable['branch']}"
        delta = _write_review_delta(
            state_root, config, base_ref=base_ref, candidate_commit=existing
        )
        template = _review_template(state_root, branch, existing, delta)
        return {
            "status": "already-prepared",
            "releaseId": manifest["releaseId"],
            "branch": branch,
            "commit": existing,
            "preparedCommit": recorded.get("preparedCommit"),
            "reviewTemplate": str(template),
            "reviewDelta": str(delta),
        }
    _run(["git", "fetch", remote, stable["branch"]], PROJECT_ROOT)
    base_ref = f"{remote}/{stable['branch']}"
    base_tree = git(PROJECT_ROOT, "rev-parse", f"{base_ref}^{{tree}}")
    branch = _branch_name(config, manifest["releaseId"])

    existing = _remote_sha(push_target, branch, PROJECT_ROOT)
    if existing:
        raise MainReleaseError(
            f"远端已存在未被当前 Preview 记录的分支：{branch}@{existing[:12]}；"
            "先运行 reconcile 交给 AI 对账，不自动覆盖"
        )

    with tempfile.TemporaryDirectory(prefix="spider-public-candidate-") as temp_name:
        worktree = Path(temp_name) / "worktree"
        _run(["git", "worktree", "add", "--detach", str(worktree), base_ref], PROJECT_ROOT)
        try:
            mode, previous_managed = stable_command._release_mode(worktree, config, base_tree)
            stable_command._synchronize_candidate(
                worktree,
                state_root / "candidate",
                mode,
                previous_managed,
            )
            _run(["git", "add", "-A"], worktree)
            diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree, check=False)
            if diff.returncode == 0:
                commit = git(PROJECT_ROOT, "rev-parse", base_ref)
            else:
                _run(["git", "commit", "-m", f"准备 Spider {manifest['version']} 公开候选"], worktree)
                commit = _run(["git", "rev-parse", "HEAD"], worktree).stdout.strip()
            tree = _run(["git", "rev-parse", "HEAD^{tree}"], worktree).stdout.strip()
            _run(["git", "push", push_target, f"HEAD:refs/heads/{branch}"], worktree)
            if _remote_sha(push_target, branch, worktree) != commit:
                raise MainReleaseError("临时公开候选分支远端回读 Commit 不一致")
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

    manifest["reviewBranch"] = {
        "name": branch,
        "remote": push_target,
        "preparedCommit": commit,
        "preparedTree": tree,
        "releaseMode": mode,
    }
    _write_manifest(state_root, manifest)
    delta = _write_review_delta(
        state_root, config, base_ref=base_ref, candidate_commit=commit
    )
    template = _review_template(state_root, branch, commit, delta)
    return {
        "status": "prepared",
        "releaseId": manifest["releaseId"],
        "branch": branch,
        "commit": commit,
        "tree": tree,
        "releaseMode": mode,
        "reviewTemplate": str(template),
        "reviewDelta": str(delta),
    }


def _copy_managed(worktree: Path, candidate: Path, managed: list[str]) -> None:
    if candidate.exists():
        shutil.rmtree(candidate)
    candidate.mkdir(parents=True)
    for value in managed:
        source = worktree / value
        target = candidate / value
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def approve(*, review_report: Path) -> dict[str, Any]:
    config = load_runtime()
    state_root, manifest = stable_command._load_latest(PROJECT_ROOT, config)
    review_branch = manifest.get("reviewBranch")
    if not isinstance(review_branch, dict):
        raise MainReleaseError("尚未创建临时公开候选分支；先执行 prepare --confirm")
    branch = str(review_branch["name"])
    remote, push_target = _stable_remote(config)
    _run(["git", "fetch", push_target, branch], PROJECT_ROOT)
    commit = _remote_sha(push_target, branch, PROJECT_ROOT)
    if not commit:
        raise MainReleaseError(f"远端临时候选分支不存在：{branch}")
    prepared = str(review_branch["preparedCommit"])
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", prepared, commit],
        cwd=PROJECT_ROOT,
        check=False,
    )
    if ancestor.returncode != 0:
        raise MainReleaseError("AI 候选不是机械 Preview Commit 的后代")

    # Validate the report before doing heavier packaging work.
    from script.project.main_release_gate import validate_review_report
    validate_review_report(review_report, branch=branch, commit=commit)

    with tempfile.TemporaryDirectory(prefix="spider-reviewed-candidate-") as temp_name:
        worktree = Path(temp_name) / "worktree"
        _run(["git", "worktree", "add", "--detach", str(worktree), commit], PROJECT_ROOT)
        try:
            inspected = inspect_candidate(worktree, config)
            _run(
                [sys.executable, "-m", "compileall", "-q", "automation", "configs", "service", "util"],
                worktree,
            )
            _copy_managed(worktree, state_root / "candidate", inspected["managedFiles"])
            tree = _run(["git", "rev-parse", "HEAD^{tree}"], worktree).stdout.strip()
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

    records = stable_command._candidate_records(state_root / "candidate")
    manifest["schemaVersion"] = max(int(manifest.get("schemaVersion", 0)), 7)
    manifest["stage"] = "ai-reviewed"
    candidate_content_sha256 = stable_command._candidate_hash(records)
    candidate_archive_sha256 = stable_command._write_candidate_archive(state_root / "candidate", state_root / "candidate.zip")
    manifest["candidateSha256"] = candidate_content_sha256
    manifest["candidateContentSha256"] = candidate_content_sha256
    manifest["candidateArchiveSha256"] = candidate_archive_sha256
    manifest["candidateArchivePath"] = "candidate.zip"
    manifest["files"] = records
    manifest["contentManifest"] = inspected["manifest"]
    manifest["publicContentAudit"] = inspected["publicContentAudit"]
    manifest["reviewBranch"].update({
        "approvedCommit": commit,
        "approvedTree": tree,
    })
    manifest["mainPublished"] = False
    manifest["published"] = False
    manifest_path = _write_manifest(state_root, manifest)
    gate = open_gate(
        PROJECT_ROOT,
        config,
        manifest=manifest,
        candidate_branch=branch,
        candidate_commit=commit,
        candidate_tree=tree,
        review_report=review_report,
        manifest_sha256=stable_command._sha256(manifest_path),
    )
    return {
        "status": "approved",
        "releaseId": manifest["releaseId"],
        "branch": branch,
        "commit": commit,
        "candidateSha256": manifest["candidateSha256"],
        "gate": str(gate_path(PROJECT_ROOT, config)),
        "next": "merge the reviewed candidate branch into main, then run ./flow stable --confirm",
        "gateState": gate["status"],
    }


def reconcile(*, mark: bool) -> dict[str, Any]:
    config = load_runtime()
    gate = load_gate(PROJECT_ROOT, config)
    facts: dict[str, Any] = {"gate": gate, "gatePath": str(gate_path(PROJECT_ROOT, config))}
    try:
        if gate.get("releaseId"):
            state_root = PROJECT_ROOT / config["stable"]["previewRoot"] / str(gate["releaseId"])
            manifest = json.loads((state_root / "candidate-manifest.json").read_text(encoding="utf-8"))
        else:
            state_root, manifest = stable_command._load_latest(PROJECT_ROOT, config, require_source_head=False)
        facts["preview"] = {
            "releaseId": manifest["releaseId"],
            "sourceCommit": manifest["sourceCommit"],
            "candidateSha256": manifest["candidateSha256"],
            "manifestPath": str(state_root / "candidate-manifest.json"),
        }
    except Exception as exc:
        facts["previewError"] = str(exc)
        manifest = None

    if gate.get("status") in {"open", "stale"}:
        _, push_target = _stable_remote(config)
        branch = str(gate.get("candidateBranch", ""))
        try:
            remote_candidate = _remote_sha(push_target, branch, PROJECT_ROOT)
        except Exception as exc:
            remote_candidate = ""
            facts["candidateRemoteError"] = str(exc)
        facts["candidateRemoteCommit"] = remote_candidate
        facts["candidateMatchesGate"] = remote_candidate == gate.get("candidateCommit")
        stable = config["git"]["stable"]
        try:
            _run(["git", "fetch", stable["remote"], stable["branch"]], PROJECT_ROOT)
            main_commit = git(PROJECT_ROOT, "rev-parse", f"{stable['remote']}/{stable['branch']}")
            facts["mainCommit"] = main_commit
            ancestor = subprocess.run(
                ["git", "merge-base", "--is-ancestor", str(gate.get("candidateCommit")), main_commit],
                cwd=PROJECT_ROOT,
                check=False,
            )
            facts["candidateMergedIntoMain"] = ancestor.returncode == 0
        except Exception as exc:
            facts["mainRemoteError"] = str(exc)

        if mark and not facts.get("candidateMatchesGate", False) and gate.get("status") == "open":
            gate = mark_stale(
                PROJECT_ROOT,
                config,
                gate,
                "候选分支 Commit 与 AI 审核门禁不一致",
                {"remoteCandidateCommit": remote_candidate},
            )
            facts["gate"] = gate
    return facts


def _print(value: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Spider public-main review collaboration")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare", help="build and push the temporary Stable review branch")
    prepare_parser.add_argument("--confirm", action="store_true")
    prepare_parser.add_argument("--json", action="store_true")
    beta_parser = sub.add_parser("prepare-beta", help="build and push an isolated immutable Beta public snapshot")
    beta_parser.add_argument("--confirm", action="store_true")
    beta_parser.add_argument("--json", action="store_true")
    approve_parser = sub.add_parser("approve", help="open the one-shot gate for an AI-reviewed commit")
    approve_parser.add_argument("--review-report", required=True, type=Path)
    approve_parser.add_argument("--json", action="store_true")
    reconcile_parser = sub.add_parser("reconcile", help="collect facts for AI-assisted state repair")
    reconcile_parser.add_argument("--mark-stale", action="store_true")
    reconcile_parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            value = prepare(confirm=args.confirm)
        elif args.command == "prepare-beta":
            value = prepare_beta(confirm=args.confirm)
        elif args.command == "approve":
            value = approve(review_report=args.review_report.expanduser().resolve())
        else:
            value = reconcile(mark=args.mark_stale)
        _print(value, args.json)
        return 0
    except (MainReleaseError, MainReleaseGateError, PublicCandidateError, stable_command.StableReleaseError, OSError, ValueError) as exc:
        _print({"status": "error", "error": str(exc)}, args.json)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
