from __future__ import annotations

import fnmatch
import hashlib
import importlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .quality_command import run as run_check
from .command_support import check_evidence_valid, git, local_config, result
from ._common import ProjectCommandError
from .main_release_gate import CLOSED, OPEN, STALE, close_gate, load_gate, mark_stale, refresh_manifest_binding
from .ownership import classify_path, git_dirty_paths, split_paths


class StableReleaseError(RuntimeError):
    pass


class StablePreviewStaleError(StableReleaseError):
    """The frozen mechanical Preview no longer matches its source state."""



def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or f"命令失败：{command}").strip()
        raise StableReleaseError(detail)
    return completed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_hash(config: dict) -> str:
    stable = json.dumps(config["stable"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def _matches(path: str, pattern: str) -> bool:
    path = path.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    return path == pattern.rstrip("/") or path.startswith(pattern.rstrip("/") + "/") or fnmatch.fnmatch(path, pattern)


def _safe_relative(value: str) -> Path:
    pure = PurePosixPath(value)
    if not value or pure.is_absolute() or ".." in pure.parts or ".git" in pure.parts:
        raise StableReleaseError(f"公开内容清单包含不安全路径：{value!r}")
    return Path(*pure.parts)


def _tracked_files(root: Path) -> list[str]:
    raw = subprocess.run(
        ["git", "ls-files", "-z", "--cached"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    values: list[str] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        relative = item.decode("utf-8")
        path = root / relative
        if path.is_symlink():
            raise StableReleaseError(f"Stable 候选不允许符号链接：{relative}")
        if path.is_file():
            values.append(relative)
    return sorted(set(values))


def _file_records(root: Path, paths: list[str]) -> list[dict]:
    return [
        {
            "path": relative,
            "sha256": _sha256(root / relative),
            "sizeBytes": (root / relative).stat().st_size,
        }
        for relative in sorted(paths)
    ]


def _workspace_source_state(root: Path) -> dict:
    dirty = split_paths(root, git_dirty_paths(root))
    if dirty["project-owned"]:
        shown = "\n".join(f"- {value}" for value in dirty["project-owned"][:20])
        more = len(dirty["project-owned"]) - 20
        suffix = f"\n- ... 另有 {more} 项" if more > 0 else ""
        raise StableReleaseError(
            "Stable Preview 检测到未提交的 project-owned 变化；先提交并 push dev：\n"
            + shown
            + suffix
        )
    return {
        "generatedDirtyCount": len(dirty["generated-state"]),
        "localPreservedDirtyCount": len(dirty["local-preserved"]),
    }


def _public_paths(root: Path, config: dict) -> list[str]:
    include = config["stable"]["include"]
    internal = config["stable"]["internalOnly"]
    generated = set(config["stable"].get("generated", []))
    selected = []
    for relative in _tracked_files(root):
        if any(_matches(relative, pattern) for pattern in include) and not any(_matches(relative, pattern) for pattern in internal):
            selected.append(relative)
    for required in config["stable"]["required"]:
        if required in generated:
            continue
        if required not in selected or not (root / required).is_file():
            raise StableReleaseError(f"Stable 候选缺少必要文件：{required}")
    leaked = [path for path in selected if any(_matches(path, pattern) for pattern in internal)]
    if leaked:
        raise StableReleaseError("内部文件进入 Stable 候选：\n" + "\n".join(leaked))
    return sorted(set(selected))


def _load_builder(value: str):
    module_name, function = value.split(":", 1)
    return getattr(importlib.import_module(module_name), function)


def _candidate_hash(files: list[dict]) -> str:
    digest = hashlib.sha256()
    for item in files:
        digest.update(item["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(item["sha256"].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _candidate_records(candidate: Path) -> list[dict]:
    records = []
    for path in sorted(candidate.rglob("*")):
        if path.is_file():
            records.append({
                "path": path.relative_to(candidate).as_posix(),
                "sha256": _sha256(path),
                "sizeBytes": path.stat().st_size,
            })
    return records


def _content_contract(config: dict) -> dict:
    value = config["stable"].get("contentManifest")
    if not isinstance(value, dict):
        raise StableReleaseError("Stable 缺少 contentManifest 契约")
    required = {"path", "mode", "allowedLegacyTrees", "legacyPaths"}
    missing = sorted(required - set(value))
    if missing:
        raise StableReleaseError(f"contentManifest 缺少字段：{missing}")
    if value["mode"] != "one-time-full-then-managed":
        raise StableReleaseError("不支持的 Stable 内容同步模式")
    _safe_relative(str(value["path"]))
    legacy = value.get("legacyPaths")
    if not isinstance(legacy, list):
        raise StableReleaseError("contentManifest legacyPaths 必须是数组")
    for item in legacy:
        _safe_relative(str(item))
    return value


def _write_public_gitignore(candidate: Path, config: dict) -> Path:
    values = config["stable"].get("publicGitignore")
    if not isinstance(values, list) or not values or any(not str(value).strip() for value in values):
        raise StableReleaseError("Public Snapshot 缺少 publicGitignore 契约")
    path = candidate / ".gitignore"
    path.write_text("# Generated public checkout ignores\n" + "\n".join(str(value) for value in values) + "\n", encoding="utf-8")
    return path


def _write_candidate_archive(candidate: Path, output: Path) -> str:
    temporary = output.with_suffix(output.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(candidate.rglob("*")):
            if not source.is_file() or source.is_symlink():
                continue
            relative = source.relative_to(candidate).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
            info.external_attr = (mode & 0xFFFF) << 16
            archive.writestr(info, source.read_bytes())
    temporary.replace(output)
    return _sha256(output)


def _write_public_content_manifest(candidate: Path, config: dict, source_commit: str, version: str) -> dict:
    contract = _content_contract(config)
    manifest_path = _safe_relative(str(contract["path"]))
    managed = sorted(
        path.relative_to(candidate).as_posix()
        for path in candidate.rglob("*")
        if path.is_file() and path.relative_to(candidate) != manifest_path
    )
    managed.append(manifest_path.as_posix())
    value = {
        "schemaVersion": 2,
        "project": config["project"]["id"],
        "version": version,
        "sourceCommit": source_commit,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "managedFiles": managed,
    }
    target = candidate / manifest_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return value


def _run_release_policy_check(root: Path, config: dict) -> None:
    profile = str(config["stable"].get("releaseCheckProfile", "")).strip()
    if not profile:
        raise StableReleaseError("Stable 未配置发布策略检查 Profile")
    check_result = run_check(root, [f"--{profile}", "--machine"], config, None)
    if check_result.get("exitCode"):
        raise StableReleaseError("公开发布策略检查未通过")



def _preview(root: Path, config: dict) -> tuple[Path, dict]:
    # Stable consumes committed public code only. Generated-state and local
    # caches may exist, but neither enters nor invalidates the main candidate.
    _workspace_source_state(root)
    branch = git(root, "branch", "--show-current", check=False)
    if branch != config["git"]["development"]["branch"]:
        raise StableReleaseError(f"Stable Preview 必须从 {config['git']['development']['branch']} 执行")
    if not check_evidence_valid(root, "full"):
        check_result = run_check(root, ["--full", "--machine"], config, None)
        if check_result.get("exitCode"):
            raise StableReleaseError("完整检查未通过")
    _run_release_policy_check(root, config)
    source_state = _workspace_source_state(root)
    source_commit = git(root, "rev-parse", "HEAD")
    source_tree = git(root, "rev-parse", "HEAD^{tree}")
    version = (root / config["project"]["versionFile"]).read_text("utf-8").strip()
    release_id = f"{version}-{source_commit[:12]}"
    state_root = root / config["stable"]["previewRoot"] / release_id
    candidate = state_root / "candidate"
    if candidate.exists():
        shutil.rmtree(candidate)
    candidate.mkdir(parents=True)
    selected = _public_paths(root, config)
    for relative in selected:
        source = root / relative
        if not source.is_file():
            continue
        target = candidate / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    content, aggregate = _load_builder(config["stable"]["summary"]["builder"])()
    (candidate / "RELEASE-NOTES.md").write_text(content, encoding="utf-8")
    _write_public_gitignore(candidate, config)
    (state_root / "internal-release-aggregate.json").write_text(json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    public_manifest = _write_public_content_manifest(candidate, config, source_commit, version)
    from script.project.main_boundary import MainBoundaryError, write_reports
    from script.project.public_content_audit import PublicContentAuditError, inspect_public_text
    try:
        write_reports(candidate, config["stable"], state_root / "main-boundary")
        public_audit = inspect_public_text(candidate, config["stable"])
    except (MainBoundaryError, PublicContentAuditError) as exc:
        raise StableReleaseError(f"Public Snapshot 边界验证失败：{exc}") from exc
    (state_root / "public-content-audit.json").write_text(
        json.dumps(public_audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    records = _candidate_records(candidate)
    required_generated = set(config["stable"].get("generated", []))
    actual = {item["path"] for item in records}
    missing_generated = sorted(required_generated - actual)
    if missing_generated:
        raise StableReleaseError(f"Stable 候选缺少生成文件：{missing_generated}")
    candidate_content_sha256 = _candidate_hash(records)
    archive_path = state_root / "candidate.zip"
    candidate_archive_sha256 = _write_candidate_archive(candidate, archive_path)
    manifest = {
        "schemaVersion": 7,
        "releaseId": release_id,
        "project": config["project"]["id"],
        "version": version,
        "sourceCommit": source_commit,
        "sourceTree": source_tree,
        "stableConfigSha256": _config_hash(config),
        "sourceState": source_state,
        "candidateSha256": candidate_content_sha256,
        "candidateContentSha256": candidate_content_sha256,
        "candidateArchiveSha256": candidate_archive_sha256,
        "candidateArchivePath": "candidate.zip",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "files": records,
        "contentManifest": public_manifest,
        "publicContentAudit": public_audit,
        "publicContentPolicy": config["stable"].get("policy"),
        "stage": "mechanical-preview",
        "remoteWrites": False,
        "mainPublished": False,
        "published": False,
    }
    (state_root / "candidate-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest = root / config["stable"]["previewRoot"] / "latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps({"releaseId": release_id}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return state_root, manifest


def _load_latest(
    root: Path,
    config: dict,
    *,
    require_source_head: bool = True,
) -> tuple[Path, dict]:
    latest_path = root / config["stable"]["previewRoot"] / "latest.json"
    if not latest_path.is_file():
        raise StableReleaseError("没有有效 Stable Preview；先执行 ./flow stable --preview")
    release_id = json.loads(latest_path.read_text("utf-8"))["releaseId"]
    state_root = root / config["stable"]["previewRoot"] / release_id
    manifest = json.loads((state_root / "candidate-manifest.json").read_text("utf-8"))
    if manifest.get("schemaVersion") not in {3, 4, 5, 6, 7}:
        raise StableReleaseError("不支持的 Stable Candidate Manifest")
    if require_source_head and manifest["sourceCommit"] != git(root, "rev-parse", "HEAD"):
        raise StablePreviewStaleError("Stable Preview 已过期：HEAD 已变化")
    if require_source_head and manifest["sourceTree"] != git(root, "rev-parse", "HEAD^{tree}"):
        raise StablePreviewStaleError("Stable Preview 已过期：Git tree 已变化")
    if manifest["stableConfigSha256"] != _config_hash(config):
        raise StablePreviewStaleError("Stable Preview 已过期：Stable 配置已变化")
    candidate = state_root / "candidate"
    records = _candidate_records(candidate)
    content_hash = _candidate_hash(records)
    expected_content = manifest.get("candidateContentSha256") or manifest.get("candidateSha256")
    if content_hash != expected_content or manifest.get("candidateSha256") != expected_content:
        raise StableReleaseError("Stable Candidate 内容被修改")
    archive_relative = str(manifest.get("candidateArchivePath") or "candidate.zip")
    archive_path = state_root / _safe_relative(archive_relative)
    if manifest.get("schemaVersion", 0) >= 7:
        if not archive_path.is_file() or _sha256(archive_path) != manifest.get("candidateArchiveSha256"):
            raise StableReleaseError("Stable Candidate Archive 丢失或内容变化")
    return state_root, manifest


def _read_previous_content_manifest(worktree: Path, config: dict) -> dict | None:
    contract = _content_contract(config)
    candidates = [str(contract["path"]), *[str(value) for value in contract.get("legacyPaths", [])]]
    for relative_value in candidates:
        path = worktree / _safe_relative(relative_value)
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError) as exc:
            raise StableReleaseError(f"远端公开内容清单无法读取：{exc}") from exc
        if not isinstance(value, dict) or value.get("schemaVersion") not in {1, 2}:
            raise StableReleaseError("远端公开内容清单 Schema 无效")
        if value.get("project") != config["project"]["id"]:
            raise StableReleaseError("远端公开内容清单项目不匹配")
        files = value.get("managedFiles")
        if not isinstance(files, list) or not files:
            raise StableReleaseError("远端公开内容清单缺少 managedFiles")
        normalized: list[str] = []
        for item in files:
            if not isinstance(item, str):
                raise StableReleaseError("远端公开内容清单路径类型无效")
            normalized.append(_safe_relative(item).as_posix())
        if len(normalized) != len(set(normalized)):
            raise StableReleaseError("远端公开内容清单包含重复路径")
        result = dict(value)
        result["managedFiles"] = normalized
        result["manifestPath"] = relative_value
        return result
    return None


def _release_mode(worktree: Path, config: dict, base_tree: str) -> tuple[str, set[str]]:
    contract = _content_contract(config)
    previous = _read_previous_content_manifest(worktree, config)
    if previous is not None:
        return "managed-incremental", set(previous["managedFiles"])
    allowed = {str(item) for item in contract["allowedLegacyTrees"]}
    if base_tree not in allowed:
        raise StableReleaseError(
            "远端缺少公开内容清单，且当前 tree 不在一次性清理授权列表；"
            "为防止重复全量清理，发布已停止"
        )
    return "one-time-full-cleanup", set()


def _remove_managed_paths(worktree: Path, paths: set[str]) -> None:
    for value in sorted(paths, key=lambda item: (item.count("/"), item), reverse=True):
        relative = _safe_relative(value)
        target = worktree / relative
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        parent = target.parent
        while parent != worktree and parent.exists():
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def _copy_candidate(candidate: Path, worktree: Path) -> None:
    for source in candidate.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(candidate)
        target = worktree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _synchronize_candidate(worktree: Path, candidate: Path, mode: str, previous_managed: set[str]) -> None:
    candidate_paths = {path.relative_to(candidate).as_posix() for path in candidate.rglob("*") if path.is_file()}
    if mode == "one-time-full-cleanup":
        _run(["git", "rm", "-r", "-f", "--ignore-unmatch", "."], worktree)
    elif mode == "managed-incremental":
        _remove_managed_paths(worktree, previous_managed - candidate_paths)
    else:
        raise StableReleaseError(f"未知发布同步模式：{mode}")
    _copy_candidate(candidate, worktree)


def _remote_branch_sha(target: str, branch: str, root: Path) -> str:
    completed = _run(["git", "ls-remote", target, f"refs/heads/{branch}"], root)
    line = completed.stdout.strip()
    return line.split()[0] if line else ""


def _stable_push_target(root: Path, config: dict) -> str:
    stable = config["git"]["stable"]
    local = local_config(root)
    return local.get("git", {}).get("stable", {}).get("pushUrl", "") or stable["remote"]


def _manifest_path(state_root: Path) -> Path:
    return state_root / "candidate-manifest.json"


def _verify_open_gate(root: Path, config: dict, state_root: Path, manifest: dict) -> dict:
    gate = load_gate(root, config)
    if gate.get("status") == CLOSED:
        raise StableReleaseError("main 发布门禁尚未打开；先完成临时分支 AI 审核")
    if gate.get("status") == STALE:
        raise StableReleaseError(
            "main 发布门禁已失效：" + str(gate.get("staleReason", "候选状态不一致"))
        )
    if gate.get("status") != OPEN:
        raise StableReleaseError("main 发布门禁状态无效")
    facts = {
        "releaseId": manifest.get("releaseId"),
        "candidateSha256": manifest.get("candidateSha256"),
        "candidateManifestSha256": _sha256(_manifest_path(state_root)),
    }
    expected = {
        "releaseId": gate.get("releaseId"),
        "candidateSha256": gate.get("candidateSha256"),
        "candidateManifestSha256": gate.get("candidateManifestSha256"),
    }
    if facts != expected:
        mark_stale(root, config, gate, "Stable Candidate 与 AI 审核门禁不一致", facts)
        raise StableReleaseError("main 发布门禁已因 Candidate 漂移自动失效")
    report = root / str(gate.get("reviewReport", ""))
    if not report.is_file() or _sha256(report) != gate.get("reviewReportSha256"):
        mark_stale(root, config, gate, "AI 审核报告丢失或内容变化")
        raise StableReleaseError("main 发布门禁已因审核报告变化自动失效")
    push_target = _stable_push_target(root, config)
    branch = str(gate.get("candidateBranch", ""))
    remote_sha = _remote_branch_sha(push_target, branch, root)
    if remote_sha != gate.get("candidateCommit"):
        mark_stale(
            root,
            config,
            gate,
            "候选分支在 AI 审核后发生变化",
            {"reviewedCommit": gate.get("candidateCommit"), "remoteCommit": remote_sha},
        )
        raise StableReleaseError("main 发布门禁已因候选分支变化自动失效")
    _run(["git", "fetch", push_target, branch], root)
    return gate


def _main_contains_reviewed_candidate(root: Path, config: dict, gate: dict, manifest: dict) -> tuple[bool, str, str | None]:
    stable = config["git"]["stable"]
    _run(["git", "fetch", stable["remote"], stable["branch"]], root)
    main_ref = f"{stable['remote']}/{stable['branch']}"
    main_commit = git(root, "rev-parse", main_ref)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", str(gate["candidateCommit"]), main_commit],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    with tempfile.TemporaryDirectory(prefix="spider-main-verify-") as temp_name:
        worktree = Path(temp_name) / "worktree"
        _run(["git", "worktree", "add", "--detach", str(worktree), main_ref], root)
        try:
            for record in manifest["files"]:
                path = worktree / record["path"]
                if not path.is_file():
                    return False, main_commit, f"main 缺少审核文件：{record['path']}"
                if _sha256(path) != record["sha256"] or path.stat().st_size != record["sizeBytes"]:
                    return False, main_commit, f"main 文件与审核候选不一致：{record['path']}"
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
    # Exact managed content is authoritative and also supports an intentional
    # squash merge.  Ancestry is still useful evidence, but not mandatory when
    # every approved public file is byte-identical on main.
    return True, main_commit, None if ancestor.returncode == 0 else "squash-merged-content-match"



def _build_stable_release_receipt(manifest: dict, gate: dict, main_commit: str) -> dict:
    return {
        "schemaVersion": 2,
        "releaseId": str(manifest["releaseId"]),
        "version": str(manifest["version"]),
        "sourceDevCommit": str(manifest["sourceCommit"]),
        "reviewedCandidateCommit": str(gate["candidateCommit"]),
        "mainCommit": str(main_commit),
        "candidateSha256": str(manifest["candidateSha256"]),
        "candidateContentSha256": str(
            manifest.get("candidateContentSha256", manifest["candidateSha256"])
        ),
        "candidateArchiveSha256": manifest.get("candidateArchiveSha256"),
        "publicIsolation": (manifest.get("publicContentAudit") or {}).get("publicIsolation"),
        "completedAt": str(manifest["publishedAt"]),
    }

def _release(root: Path, args: list[str], config: dict):
    gate = load_gate(root, config)
    if gate.get("status") == CLOSED:
        return result(
            "等待人工审核",
            "main 发布门禁未打开，Flow 不会创建临时分支或直接修改 main",
            [],
            ["尚未完成 AI 语义净化与人工 Diff 审核"],
            "git push origin dev；然后执行 uv run --locked python script/project/main_release.py prepare --confirm",
            "无需回滚",
            20,
        )
    release_id = str(gate.get("releaseId", ""))
    if not release_id:
        raise StableReleaseError("main 发布门禁缺少 releaseId")
    state_root = root / config["stable"]["previewRoot"] / release_id
    manifest_path = _manifest_path(state_root)
    if not manifest_path.is_file():
        raise StableReleaseError("门禁对应的 Stable Candidate 已丢失")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidate = state_root / "candidate"
    records = _candidate_records(candidate)
    if _candidate_hash(records) != manifest.get("candidateSha256"):
        mark_stale(root, config, gate, "本地 Stable Candidate 内容变化")
        raise StableReleaseError("main 发布门禁已因本地 Candidate 变化自动失效")
    gate = _verify_open_gate(root, config, state_root, manifest)
    merged, main_commit, mismatch = _main_contains_reviewed_candidate(root, config, gate, manifest)
    if not merged:
        return result(
            "等待合并",
            f"AI 审核门禁已打开：{gate['candidateBranch']}@{str(gate['candidateCommit'])[:12]}",
            [
                f"Release ID：{release_id}",
                "门禁与候选 Commit、Manifest、审核报告一致",
            ],
            [mismatch or "候选尚未进入 main"],
            f"人工审核 Diff 后，将 {gate['candidateBranch']} 合并到 main；随后执行 ./flow stable --confirm",
            "候选分支仍保留；不需要回滚 Flow",
            20,
        )

    manifest["mainPublished"] = True
    manifest["mainPublishedCommit"] = main_commit
    manifest["published"] = True
    manifest["publishedAt"] = datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = _build_stable_release_receipt(manifest, gate, main_commit)
    _, archive_path = close_gate(root, config, gate=gate, receipt=receipt)
    return result(
        "成功",
        f"Stable main 已与审核候选对账，main 发布门禁已关闭：{main_commit[:12]}",
        [
            f"Release ID：{release_id}",
            "main 管理文件与 AI 审核候选逐文件一致",
            "npm 与 online 数据发布由独立 GitHub Release Action 负责",
            f"发布 Receipt：{archive_path.relative_to(root)}",
        ],
        [],
        "数据候选需要发布时，使用 GitHub data-build / release 工作流",
        "远端 main 需要补偿时使用后续 Git 修复提交",
    )

def _guide(root: Path, config: dict):
    gate = load_gate(root, config)
    if gate.get("status") == OPEN:
        return result(
            "已审核",
            f"AI 审核门禁已打开：{gate.get('candidateBranch')}@{str(gate.get('candidateCommit', ''))[:12]}",
            ["门禁只允许该精确 Commit 发布；候选变化会自动失效"],
            [],
            "人工审核最终 Diff 并合并到 main，然后执行 ./flow stable --confirm",
            "运行 uv run --locked python script/project/main_release.py reconcile --mark-stale 可生成状态事实并标记漂移",
        )
    if gate.get("status") == STALE:
        return result(
            "门禁失效",
            str(gate.get("staleReason", "候选状态不同步")),
            [],
            ["旧 AI 审核不能继续使用"],
            "uv run --locked python script/project/main_release.py reconcile --mark-stale；修复后重新审核并 approve",
            "门禁是 generated-state，可由 AI 根据 Git、Manifest 与 Receipt 事实重建",
            20,
        )
    return result(
        "等待人工流程",
        "Stable main 属于低频特殊发布；Flow 只提示步骤并消费最终审核门禁",
        ["Flow 不创建临时分支、不调用 AI、不合并 main"],
        ["当前没有 OPEN 的 AI 审核门禁"],
        "git push origin dev；然后执行 uv run --locked python script/project/main_release.py prepare --confirm",
        "候选与门禁均位于 .flow/state，可删除后重新准备",
    )


def preview_command(root: Path, args: list[str], config: dict, loader):
    return result(
        "已迁移",
        "Stable Preview 是项目低频人工协作逻辑，不再由 Flow 直接执行",
        [],
        ["未生成候选、未修改远端"],
        "uv run --locked python script/project/main_release.py prepare --confirm",
        "无需回滚",
    )


def release_command(root: Path, args: list[str], config: dict, loader):
    return _release(root, args, config)


def run(root: Path, args: list[str], config: dict, loader):
    if "--preview" in args:
        return preview_command(root, args, config, loader)
    if "--confirm" in args or "--yes" in args:
        return _release(root, args, config)
    return _guide(root, config)
