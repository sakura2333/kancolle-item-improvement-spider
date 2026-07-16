#!/usr/bin/env python3
from __future__ import annotations

"""Project-owned collaboration around one immutable public candidate.

The project content registry decides what belongs to the public product.  Git
binds source and branch identities only; it does not classify content.  Every
release transaction separates internal evidence, the frozen candidate, review
projection, and channel results.
"""

import argparse
import hashlib
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
from script.project.release_transaction import (
    ReleaseTransaction,
    ReleaseTransactionError,
    latest_path,
)
from script.project.runtime import load as load_runtime


class MainReleaseError(RuntimeError):
    pass


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if completed.returncode:
        raise MainReleaseError((completed.stderr or completed.stdout or "命令失败").strip())
    return completed


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def _transaction(state_root: Path, manifest: dict[str, Any]) -> ReleaseTransaction:
    return ReleaseTransaction(state_root, str(manifest["releaseId"]))


def _stable_remote(config: dict) -> tuple[str, str]:
    stable = config["git"]["stable"]
    local = local_config(PROJECT_ROOT)
    push_target = local.get("git", {}).get("stable", {}).get("pushUrl", "") or stable["remote"]
    return stable["remote"], push_target


def _branch_name(config: dict, release_id: str) -> str:
    return str(config["stable"].get("candidateBranchPrefix", "public-candidate/")) + release_id


def _beta_branch_name(config: dict, release_id: str) -> str:
    return str(config["stable"].get("betaCandidateBranchPrefix", "public-beta/")) + release_id


def _remote_sha(target: str, branch: str, cwd: Path) -> str:
    completed = _run(["git", "ls-remote", target, f"refs/heads/{branch}"], cwd)
    line = completed.stdout.strip()
    return line.split()[0] if line else ""


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


def _load_or_preview(config: dict) -> tuple[Path, dict[str, Any]]:
    try:
        return stable_command._load_latest(PROJECT_ROOT, config)
    except stable_command.StablePreviewStaleError:
        return stable_command._preview(PROJECT_ROOT, config)
    except stable_command.StableReleaseError as exc:
        if "no release transaction exists" not in str(exc):
            raise
        return stable_command._preview(PROJECT_ROOT, config)


def _reset_worktree_to_candidate_snapshot(worktree: Path, candidate: Path) -> None:
    _run(["git", "rm", "-r", "-q", "--ignore-unmatch", "."], worktree)
    for untracked in worktree.iterdir():
        if untracked.name == ".git":
            continue
        if untracked.is_dir() and not untracked.is_symlink():
            shutil.rmtree(untracked)
        else:
            untracked.unlink()
    stable_command._copy_candidate(candidate, worktree)


def _push_exact_snapshot(
    *,
    candidate: Path,
    base_ref: str,
    push_target: str,
    branch: str,
    message: str,
) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="spider-public-snapshot-") as temp_name:
        worktree = Path(temp_name) / "worktree"
        _run(["git", "worktree", "add", "--detach", str(worktree), base_ref], PROJECT_ROOT)
        try:
            _reset_worktree_to_candidate_snapshot(worktree, candidate)
            _run(["git", "add", "-A"], worktree)
            diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree, check=False)
            if diff.returncode == 0:
                commit = _run(["git", "rev-parse", "HEAD"], worktree).stdout.strip()
            else:
                _run(["git", "commit", "-m", message], worktree)
                commit = _run(["git", "rev-parse", "HEAD"], worktree).stdout.strip()
            tree = _run(["git", "rev-parse", "HEAD^{tree}"], worktree).stdout.strip()
            _run(["git", "push", push_target, f"HEAD:refs/heads/{branch}"], worktree)
            if _remote_sha(push_target, branch, worktree) != commit:
                raise MainReleaseError("公开快照远端回读 Commit 不一致")
            return commit, tree
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )


def _write_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _write_review_delta(
    transaction: ReleaseTransaction,
    config: dict,
    *,
    base_ref: str,
    candidate_commit: str,
) -> Path:
    completed = _run(["git", "diff", "--name-status", "-M", base_ref, candidate_commit], PROJECT_ROOT)
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
        raise MainReleaseError("公开候选包含未分类文件；检查项目内容注册表")
    return transaction.write_internal_json(
        "stable-review-delta.json",
        {
            "schemaVersion": 1,
            "baseRef": base_ref,
            "candidateCommit": candidate_commit,
            "counts": counts,
            "changes": changes,
        },
    )


def _review_template(transaction: ReleaseTransaction, branch: str, commit: str) -> Path:
    return _write_json(
        transaction.review_channel("stable") / "ai-review-template.json",
        {
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
            "notes": "Review the immutable candidate. If cleanup is required, reject it, fix dev, and create a new release transaction.",
        },
    )


def _candidate_inventory(manifest: dict[str, Any], config: dict) -> dict[str, Any]:
    categories = config["stable"].get("categories", {})
    counts = {name: 0 for name in categories}
    counts["uncategorized"] = 0
    files: list[dict[str, str]] = []
    for record in manifest["files"]:
        relative = str(record["path"])
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
        raise MainReleaseError("冻结候选包含未分类文件")
    return {"schemaVersion": 1, "counts": counts, "files": files}


def _review_identity(
    manifest: dict[str, Any],
    *,
    channel: str,
    branch: str,
    commit: str,
    tree: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "channel": channel,
        "releaseId": manifest["releaseId"],
        "project": manifest["project"],
        "version": manifest["version"],
        "sourceCommit": manifest["sourceCommit"],
        "sourceTree": manifest["sourceTree"],
        "candidateContentSha256": manifest["candidateContentSha256"],
        "candidateArchiveSha256": manifest["candidateArchiveSha256"],
        "branch": branch,
        "commit": commit,
        "tree": tree,
    }


def _review_isolation(manifest: dict[str, Any]) -> dict[str, Any]:
    audit = manifest.get("publicContentAudit") or {}
    isolation = audit.get("publicIsolation") or {}
    return {
        "schemaVersion": 1,
        "policy": manifest.get("publicContentPolicy"),
        "findingCount": audit.get("findingCount", 0),
        "publicIsolation": isolation,
    }


def _write_review_projection(
    transaction: ReleaseTransaction,
    config: dict,
    manifest: dict[str, Any],
    *,
    channel: str,
    branch: str,
    commit: str,
    tree: str,
) -> tuple[Path, str]:
    review_root = transaction.review_channel(channel)
    if review_root.exists():
        shutil.rmtree(review_root)
    review_root.mkdir(parents=True)

    entries: dict[str, bytes] = {}
    entries["review-identity.json"] = (
        json.dumps(_review_identity(manifest, channel=channel, branch=branch, commit=commit, tree=tree), ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    inventory = _candidate_inventory(manifest, config)
    inventory["publicIsolation"] = (manifest.get("publicContentAudit") or {}).get("publicIsolation")
    entries["candidate-inventory.json"] = (json.dumps(inventory, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    entries["public-isolation-summary.json"] = (
        json.dumps(_review_isolation(manifest), ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    exceptions = config["stable"].get("publicExceptions") or {}
    entries["public-exceptions.json"] = (json.dumps(exceptions, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    entries["candidate-files.txt"] = (
        "".join(f"{record['path']}\t{record['sha256']}\t{record['sizeBytes']}\n" for record in manifest["files"])
    ).encode("utf-8")
    public_manifest = transaction.candidate_public / "PUBLIC-CONTENT-MANIFEST.json"
    if not public_manifest.is_file():
        raise MainReleaseError("冻结候选缺少 PUBLIC-CONTENT-MANIFEST.json")
    entries["PUBLIC-CONTENT-MANIFEST.json"] = public_manifest.read_bytes()
    entries["candidate.zip"] = transaction.candidate_archive.read_bytes()

    for name, data in entries.items():
        (review_root / name).write_bytes(data)
    review_manifest = {
        "schemaVersion": 1,
        "releaseId": manifest["releaseId"],
        "files": [
            {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "sizeBytes": len(data)}
            for name, data in sorted(entries.items())
        ],
    }
    review_manifest_data = (json.dumps(review_manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (review_root / "review-manifest.json").write_bytes(review_manifest_data)
    entries["review-manifest.json"] = review_manifest_data

    output = review_root / "beta-ai-review.zip"
    temporary = output.with_suffix(output.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o644 & 0xFFFF) << 16
            archive.writestr(info, data)
    temporary.replace(output)
    return output, stable_command._sha256(output)


def _write_beta_receipt(
    transaction: ReleaseTransaction,
    manifest: dict[str, Any],
    *,
    branch: str,
    commit: str,
    tree: str,
    remote: str,
) -> Path:
    return transaction.write_result_json(
        "beta-receipt.json",
        {
            "schemaVersion": 4,
            "channel": "beta",
            "project": manifest["project"],
            "version": manifest["version"],
            "releaseId": manifest["releaseId"],
            "sourceCommit": manifest["sourceCommit"],
            "sourceTree": manifest["sourceTree"],
            "candidateContentSha256": manifest["candidateContentSha256"],
            "candidateArchiveSha256": manifest["candidateArchiveSha256"],
            "publicIsolation": (manifest.get("publicContentAudit") or {}).get("publicIsolation"),
            "branch": branch,
            "commit": commit,
            "tree": tree,
            "remote": remote,
            "policy": "immutable-project-registry-candidate",
            "formalVersionChanged": False,
            "mainChanged": False,
            "npmPublished": False,
            "onlinePublished": False,
        },
    )


def prepare_beta(*, confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise MainReleaseError("创建并推送隔离 Beta 公开快照需要 --confirm")
    config = load_runtime()
    _verify_dev_pushed(config)
    state_root, manifest = _load_or_preview(config)
    transaction = _transaction(state_root, manifest)
    candidate = transaction.candidate_public
    inspect_public_text(candidate, config["stable"])

    remote_name, push_target = _stable_remote(config)
    branch = _beta_branch_name(config, manifest["releaseId"])
    receipt_path = transaction.result / "beta-receipt.json"
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        existing = _remote_sha(push_target, branch, PROJECT_ROOT)
        if not existing or existing != receipt.get("commit"):
            raise MainReleaseError("Beta 分支与事务 Result 不一致；拒绝自动覆盖")
        bundle, bundle_hash = _write_review_projection(
            transaction,
            config,
            manifest,
            channel="beta",
            branch=branch,
            commit=existing,
            tree=str(receipt["tree"]),
        )
        return {
            "status": "already-prepared",
            "channel": "beta",
            "releaseId": manifest["releaseId"],
            "branch": branch,
            "commit": existing,
            "tree": receipt["tree"],
            "candidateContentSha256": manifest["candidateContentSha256"],
            "candidateArchiveSha256": manifest["candidateArchiveSha256"],
            "receipt": _relative(receipt_path),
            "reviewBundle": _relative(bundle),
            "reviewBundleSha256": bundle_hash,
        }

    existing = _remote_sha(push_target, branch, PROJECT_ROOT)
    if existing:
        raise MainReleaseError(f"远端已存在未被当前事务记录的 Beta 分支：{branch}@{existing[:12]}")
    stable = config["git"]["stable"]
    _run(["git", "fetch", stable["remote"], stable["branch"]], PROJECT_ROOT)
    base_ref = f"{stable['remote']}/{stable['branch']}"
    commit, tree = _push_exact_snapshot(
        candidate=candidate,
        base_ref=base_ref,
        push_target=push_target,
        branch=branch,
        message=f"准备 Spider {manifest['version']} Beta 公开快照",
    )
    receipt = _write_beta_receipt(
        transaction,
        manifest,
        branch=branch,
        commit=commit,
        tree=tree,
        remote=remote_name,
    )
    bundle, bundle_hash = _write_review_projection(
        transaction,
        config,
        manifest,
        channel="beta",
        branch=branch,
        commit=commit,
        tree=tree,
    )
    transaction.write_status(
        "beta-prepared",
        betaBranch=branch,
        betaCommit=commit,
        betaTree=tree,
        reviewBundleSha256=bundle_hash,
    )
    return {
        "status": "prepared",
        "channel": "beta",
        "releaseId": manifest["releaseId"],
        "branch": branch,
        "commit": commit,
        "tree": tree,
        "candidateContentSha256": manifest["candidateContentSha256"],
        "candidateArchiveSha256": manifest["candidateArchiveSha256"],
        "receipt": _relative(receipt),
        "reviewBundle": _relative(bundle),
        "reviewBundleSha256": bundle_hash,
        "next": "AI-review the immutable review bundle; reject and regenerate from dev if cleanup is needed",
    }


def prepare(*, confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise MainReleaseError("创建并推送 Stable 审核分支需要 --confirm")
    config = load_runtime()
    _verify_dev_pushed(config)
    state_root, manifest = _load_or_preview(config)
    transaction = _transaction(state_root, manifest)
    remote_name, push_target = _stable_remote(config)
    branch = _branch_name(config, manifest["releaseId"])
    result_path = transaction.result / "stable-review-prepared.json"
    stable = config["git"]["stable"]
    _run(["git", "fetch", stable["remote"], stable["branch"]], PROJECT_ROOT)
    base_ref = f"{stable['remote']}/{stable['branch']}"

    if result_path.is_file():
        recorded = json.loads(result_path.read_text(encoding="utf-8"))
        existing = _remote_sha(push_target, branch, PROJECT_ROOT)
        if not existing or existing != recorded.get("commit"):
            raise MainReleaseError("Stable 审核分支与事务 Result 不一致")
        delta = _write_review_delta(transaction, config, base_ref=base_ref, candidate_commit=existing)
        template = _review_template(transaction, branch, existing)
        return {
            "status": "already-prepared",
            "releaseId": manifest["releaseId"],
            "branch": branch,
            "commit": existing,
            "tree": recorded["tree"],
            "reviewTemplate": _relative(template),
            "reviewDelta": _relative(delta),
        }

    existing = _remote_sha(push_target, branch, PROJECT_ROOT)
    if existing:
        raise MainReleaseError(f"远端已存在未被当前事务记录的 Stable 审核分支：{branch}@{existing[:12]}")
    commit, tree = _push_exact_snapshot(
        candidate=transaction.candidate_public,
        base_ref=base_ref,
        push_target=push_target,
        branch=branch,
        message=f"准备 Spider {manifest['version']} Stable 审核快照",
    )
    prepared = {
        "schemaVersion": 1,
        "releaseId": manifest["releaseId"],
        "branch": branch,
        "remote": remote_name,
        "commit": commit,
        "tree": tree,
        "candidateContentSha256": manifest["candidateContentSha256"],
        "candidateArchiveSha256": manifest["candidateArchiveSha256"],
    }
    transaction.write_result_json("stable-review-prepared.json", prepared)
    delta = _write_review_delta(transaction, config, base_ref=base_ref, candidate_commit=commit)
    template = _review_template(transaction, branch, commit)
    transaction.write_status("stable-review-prepared", stableBranch=branch, stableCommit=commit, stableTree=tree)
    return {
        "status": "prepared",
        "releaseId": manifest["releaseId"],
        "branch": branch,
        "commit": commit,
        "tree": tree,
        "reviewTemplate": _relative(template),
        "reviewDelta": _relative(delta),
    }


def approve(*, review_report: Path) -> dict[str, Any]:
    config = load_runtime()
    state_root, manifest = stable_command._load_latest(PROJECT_ROOT, config)
    transaction = _transaction(state_root, manifest)
    prepared_path = transaction.result / "stable-review-prepared.json"
    if not prepared_path.is_file():
        raise MainReleaseError("尚未创建 Stable 审核分支；先执行 prepare --confirm")
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    branch = str(prepared["branch"])
    _, push_target = _stable_remote(config)
    _run(["git", "fetch", push_target, branch], PROJECT_ROOT)
    commit = _remote_sha(push_target, branch, PROJECT_ROOT)
    if not commit:
        raise MainReleaseError(f"远端 Stable 审核分支不存在：{branch}")
    if commit != prepared.get("commit"):
        raise MainReleaseError("审核分支在冻结后发生变化；必须修复 dev 并生成新事务")

    from script.project.main_release_gate import validate_review_report
    validate_review_report(review_report, branch=branch, commit=commit)

    with tempfile.TemporaryDirectory(prefix="spider-reviewed-candidate-") as temp_name:
        worktree = Path(temp_name) / "worktree"
        _run(["git", "worktree", "add", "--detach", str(worktree), commit], PROJECT_ROOT)
        try:
            inspected = inspect_candidate(worktree, config)
            records = stable_command._candidate_records(worktree)
            if stable_command._candidate_hash(records) != manifest["candidateContentSha256"]:
                raise MainReleaseError("审核分支内容与冻结 Candidate 不一致")
            tree = _run(["git", "rev-parse", "HEAD^{tree}"], worktree).stdout.strip()
            if tree != prepared.get("tree"):
                raise MainReleaseError("审核分支 Tree 与冻结 Result 不一致")
            if inspected["manifest"] != manifest["contentManifest"]:
                raise MainReleaseError("审核分支 Public Manifest 与冻结 Candidate 不一致")
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

    gate = open_gate(
        PROJECT_ROOT,
        config,
        manifest=manifest,
        candidate_branch=branch,
        candidate_commit=commit,
        candidate_tree=tree,
        review_report=review_report,
        manifest_sha256=stable_command._sha256(transaction.candidate_manifest),
    )
    approval = transaction.write_result_json(
        "stable-approval.json",
        {
            "schemaVersion": 1,
            "releaseId": manifest["releaseId"],
            "branch": branch,
            "commit": commit,
            "tree": tree,
            "candidateContentSha256": manifest["candidateContentSha256"],
            "reviewReportSha256": gate["reviewReportSha256"],
        },
    )
    transaction.write_status("stable-approved", stableBranch=branch, stableCommit=commit, stableTree=tree)
    return {
        "status": "approved",
        "releaseId": manifest["releaseId"],
        "branch": branch,
        "commit": commit,
        "candidateContentSha256": manifest["candidateContentSha256"],
        "approval": _relative(approval),
        "gate": _relative(gate_path(PROJECT_ROOT, config)),
        "next": "merge the exact reviewed candidate branch into main, then run ./flow stable --confirm",
        "gateState": gate["status"],
    }


def reconcile(*, mark: bool) -> dict[str, Any]:
    config = load_runtime()
    gate = load_gate(PROJECT_ROOT, config)
    facts: dict[str, Any] = {"gate": gate, "gatePath": _relative(gate_path(PROJECT_ROOT, config))}
    try:
        release_id = str(gate.get("releaseId") or "")
        if release_id:
            transaction = ReleaseTransaction.from_config(PROJECT_ROOT, config, release_id)
            manifest = transaction.load_manifest()
        else:
            state_root, manifest = stable_command._load_latest(PROJECT_ROOT, config, require_source_head=False)
            transaction = _transaction(state_root, manifest)
        facts["transaction"] = {
            "releaseId": manifest["releaseId"],
            "sourceCommit": manifest["sourceCommit"],
            "candidateContentSha256": manifest["candidateContentSha256"],
            "candidateManifest": _relative(transaction.candidate_manifest),
            "status": transaction.load_status(),
        }
    except Exception as exc:
        facts["transactionError"] = str(exc)
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
        if mark and not facts["candidateMatchesGate"] and gate.get("status") == "open":
            facts["gate"] = mark_stale(
                PROJECT_ROOT,
                config,
                gate,
                "候选分支 Commit 与审核门禁不一致",
                {"remoteCandidateCommit": remote_candidate},
            )
    return facts


def _print(value: dict[str, Any], as_json: bool) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Spider public release transaction collaboration")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare", help="push the immutable Stable review branch")
    prepare_parser.add_argument("--confirm", action="store_true")
    prepare_parser.add_argument("--json", action="store_true")
    beta_parser = sub.add_parser("prepare-beta", help="push the immutable Beta branch and build review projection")
    beta_parser.add_argument("--confirm", action="store_true")
    beta_parser.add_argument("--json", action="store_true")
    approve_parser = sub.add_parser("approve", help="approve the exact immutable Stable review commit")
    approve_parser.add_argument("--review-report", required=True, type=Path)
    approve_parser.add_argument("--json", action="store_true")
    reconcile_parser = sub.add_parser("reconcile", help="collect release transaction facts")
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
    except (
        MainReleaseError,
        MainReleaseGateError,
        PublicCandidateError,
        ReleaseTransactionError,
        stable_command.StableReleaseError,
        OSError,
        ValueError,
    ) as exc:
        _print({"status": "error", "error": str(exc)}, args.json)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
