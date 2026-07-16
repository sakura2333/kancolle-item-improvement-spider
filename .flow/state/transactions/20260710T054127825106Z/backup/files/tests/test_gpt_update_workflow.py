from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from script.flow import artifact
from script.flow import update as module
from script.project import flow_baseline


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _working_identity(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in ("VERSION", "app.txt", "validate.py", "identity.py"):
        path = root / relative
        if not path.is_file():
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _run_git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, text=True, capture_output=True)


def _init_project(base: Path) -> tuple[Path, Path]:
    root = base / "project"
    downloads = base / "downloads"
    root.mkdir()
    downloads.mkdir()
    (root / "VERSION").write_text("1.0.4-rc.1\n", encoding="utf-8")
    (root / "app.txt").write_text("before\n", encoding="utf-8")
    (root / "validate.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (root / "identity.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (root / ".flow").mkdir()
    (root / ".flow/local.json").write_text(
        json.dumps({"downloadRoot": str(downloads)}) + "\n", encoding="utf-8"
    )
    _run_git(root, "init", "-b", "dev")
    _run_git(root, "config", "user.name", "Test")
    _run_git(root, "config", "user.email", "test@example.invalid")
    _run_git(root, "add", "VERSION", "app.txt", "validate.py", "identity.py")
    _run_git(root, "commit", "-m", "baseline")
    return root, downloads


def _target_tree(root: Path, files: dict[str, bytes], delete: list[str] | None = None) -> str:
    with tempfile.TemporaryDirectory() as temp_name:
        stage = Path(temp_name) / "stage"
        _run_git(root, "worktree", "add", "--detach", str(stage), "HEAD")
        try:
            for relative, content in files.items():
                path = stage / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            for relative in delete or []:
                path = stage / relative
                if path.exists():
                    path.unlink()
            _run_git(stage, "add", "-A")
            return _git(stage, "write-tree")
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(stage)], cwd=root, check=False, capture_output=True)


def _write_package(
    path: Path,
    root: Path,
    project: str,
    files: dict[str, bytes],
    *,
    from_version: str = "1.0.4-rc.1",
    to_version: str = "1.0.4",
    delete: list[str] | None = None,
) -> Path:
    delete = delete or []
    base_identity = {"scheme": "git-tree", "value": _git(root, "rev-parse", "HEAD^{tree}")}
    target_identity = {"scheme": "git-tree", "value": _target_tree(root, files, delete)}
    manifest = {
        "schemaVersion": 1,
        "projectId": project,
        "fromVersion": from_version,
        "toVersion": to_version,
        "baseIdentity": base_identity,
        "targetIdentity": target_identity,
        "files": [
            {"path": relative, "sha256": _digest(content), "mode": 0o644}
            for relative, content in sorted(files.items())
        ],
        "delete": delete,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("update-manifest.json", json.dumps(manifest))
        for relative, content in files.items():
            archive.writestr(f"payload/{relative}", content)
    return artifact.write_sidecar(
        path,
        package_type="update",
        package_id=f"test-{to_version}",
        project_id=project,
        base_version=from_version,
        target_version=to_version,
        base_identity=base_identity,
        target_identity=target_identity,
    )


def _write_working_identity_package(
    path: Path,
    root: Path,
    files: dict[str, bytes],
    *,
    from_version: str,
    to_version: str,
) -> Path:
    base_identity = {"scheme": "working-test-sha256", "value": _working_identity(root)}
    original = {relative: (root / relative).read_bytes() for relative in files}
    try:
        for relative, content in files.items():
            (root / relative).write_bytes(content)
        target_identity = {"scheme": "working-test-sha256", "value": _working_identity(root)}
    finally:
        for relative, content in original.items():
            (root / relative).write_bytes(content)
    manifest = {
        "schemaVersion": 1,
        "projectId": "kancolle-item-improvement-spider",
        "fromVersion": from_version,
        "toVersion": to_version,
        "baseIdentity": base_identity,
        "targetIdentity": target_identity,
        "files": [
            {"path": relative, "sha256": _digest(content), "mode": 0o644}
            for relative, content in sorted(files.items())
        ],
        "delete": [],
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("update-manifest.json", json.dumps(manifest))
        for relative, content in files.items():
            archive.writestr(f"payload/{relative}", content)
    return artifact.write_sidecar(
        path,
        package_type="update",
        package_id=f"test-{to_version}",
        project_id="kancolle-item-improvement-spider",
        base_version=from_version,
        target_version=to_version,
        base_identity=base_identity,
        target_identity=target_identity,
    )


def _config(base: Path) -> dict:
    return {
        "project": {"id": "kancolle-item-improvement-spider", "versionFile": "VERSION"},
        "update": {
            "maxFileBytes": 1_000_000,
            "requiredBranch": "dev",
            "protected": [".git/**", ".flow/local.json", ".flow/state/**", ".venv/**"],
            "candidateVerifier": ["{python}", "validate.py"],
        },
        "recovery": {"outputRoot": str(base / "recovery")},
    }


class UpdateTransactionTest(unittest.TestCase):
    def test_successful_update_creates_commit_and_leaves_code_clean(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            root, downloads = _init_project(base)
            before = _git(root, "rev-parse", "HEAD")
            _write_package(
                downloads / "update.zip",
                root,
                "kancolle-item-improvement-spider",
                {"VERSION": b"1.0.4\n", "app.txt": b"after\n"},
            )
            result = module._apply_action(root, ["--yes"], _config(base))
            after = _git(root, "rev-parse", "HEAD")
            self.assertEqual(result["status"], "成功")
            self.assertNotEqual(after, before)
            self.assertEqual(
                _git(root, "log", "-1", "--pretty=%s"),
                "更新 kancolle-item-improvement-spider 1.0.4-rc.1 → 1.0.4",
            )
            self.assertEqual(module._project_dirty_paths(root, _config(base)), [])

    def test_update_with_deleted_file_stages_idempotently(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            root, downloads = _init_project(base)
            legacy_dir = root / "legacy"
            legacy_dir.mkdir()
            legacy = legacy_dir / "old.txt"
            legacy.write_text("legacy\n", encoding="utf-8")
            _run_git(root, "add", "legacy/old.txt")
            _run_git(root, "commit", "-m", "add legacy")
            _write_package(
                downloads / "update.zip",
                root,
                "kancolle-item-improvement-spider",
                {"VERSION": b"1.0.4\n", "app.txt": b"after\n"},
                delete=["legacy/old.txt"],
            )
            result = module._apply_action(root, ["--yes"], _config(base))
            self.assertEqual(result["status"], "成功")
            self.assertFalse(legacy.exists())
            self.assertFalse(legacy_dir.exists())
            self.assertNotIn("legacy/old.txt", _git(root, "ls-files"))
            self.assertEqual(module._project_dirty_paths(root, _config(base)), [])

    def test_verified_uncommitted_base_is_committed_with_next_update(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            root, downloads = _init_project(base)
            (root / "VERSION").write_text("1.0.4\n", encoding="utf-8")
            (root / "app.txt").write_text("uncommitted 1.0.4\n", encoding="utf-8")
            _write_working_identity_package(
                downloads / "update.zip",
                root,
                {"VERSION": b"1.0.5\n", "app.txt": b"after 1.0.5\n"},
                from_version="1.0.4",
                to_version="1.0.5",
            )
            original_identity = module._identity_value

            def identity(current_root: Path, scheme: str, config: dict | None = None) -> str:
                if scheme == "working-test-sha256":
                    return _working_identity(current_root)
                return original_identity(current_root, scheme, config)

            with mock.patch.object(module, "_identity_value", side_effect=identity):
                result = module._apply_action(root, ["--yes"], _config(base))
            self.assertEqual(result["status"], "成功")
            self.assertEqual((root / "VERSION").read_text("utf-8"), "1.0.5\n")
            self.assertEqual((root / "app.txt").read_text("utf-8"), "after 1.0.5\n")
            self.assertEqual(module._project_dirty_paths(root, _config(base)), [])
            self.assertEqual(
                _git(root, "log", "-1", "--pretty=%s"),
                "更新 kancolle-item-improvement-spider 1.0.4 → 1.0.5",
            )

    def test_staged_protected_state_is_unstaged_and_not_committed(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            root, downloads = _init_project(base)
            generated = root / "generated/state.json"
            generated.parent.mkdir()
            generated.write_text("generated\n", encoding="utf-8")
            _run_git(root, "add", "generated/state.json")
            _write_package(
                downloads / "update.zip",
                root,
                "kancolle-item-improvement-spider",
                {"VERSION": b"1.0.4\n", "app.txt": b"after\n"},
            )
            config = _config(base)
            config["update"]["protected"].append("generated/**")
            result = module._apply_action(root, ["--yes"], config)
            self.assertEqual(result["status"], "成功")
            self.assertEqual(generated.read_text("utf-8"), "generated\n")
            self.assertNotIn("generated/state.json", _git(root, "show", "--pretty=", "--name-only", "HEAD"))
            self.assertIn("?? generated/", _git(root, "status", "--short"))

    def test_failure_after_commit_restores_head_files_and_retry_package(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            root, downloads = _init_project(base)
            before = _git(root, "rev-parse", "HEAD")
            package = downloads / "update.zip"
            sidecar = _write_package(
                package,
                root,
                "kancolle-item-improvement-spider",
                {"VERSION": b"1.0.4\n", "app.txt": b"after\n"},
            )
            with mock.patch.object(module, "_write_metadata", side_effect=OSError("metadata failed")):
                with self.assertRaises(OSError):
                    module._apply_action(root, ["--yes"], _config(base))
            self.assertEqual(_git(root, "rev-parse", "HEAD"), before)
            self.assertEqual((root / "VERSION").read_text("utf-8"), "1.0.4-rc.1\n")
            self.assertEqual((root / "app.txt").read_text("utf-8"), "before\n")
            self.assertTrue(package.is_file())
            self.assertTrue(sidecar.is_file())
            applied = downloads / ".flow-applied/kancolle-item-improvement-spider"
            self.assertEqual(list(applied.glob("*")) if applied.exists() else [], [])

    def test_shared_download_root_uses_sidecar_project_not_directory(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            root, downloads = _init_project(base)
            _write_package(downloads / "other.zip", root, "other-project", {"VERSION": b"9.0.0\n"}, to_version="9.0.0")
            _write_package(downloads / "spider.zip", root, "kancolle-item-improvement-spider", {"VERSION": b"1.0.4\n"})
            candidate, notes = module._select(root, _config(base))
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate.path.name, "spider.zip")
            self.assertTrue(any("非本项目包" in note for note in notes))

    def test_protected_local_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            root, downloads = _init_project(base)
            sidecar = _write_package(
                downloads / "bad.zip",
                root,
                "kancolle-item-improvement-spider",
                {".flow/local.json": b"{}\n", "VERSION": b"1.0.4\n"},
            )
            candidate = module._candidate_from_sidecar(sidecar)
            with self.assertRaises(module.UpdateError):
                module._validate_targets(candidate, _config(base))

    def test_failed_staging_leaves_real_project_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            root, downloads = _init_project(base)
            (root / "validate.py").write_text("raise SystemExit(9)\n", encoding="utf-8")
            _run_git(root, "add", "validate.py")
            _run_git(root, "commit", "-m", "failing validation")
            _write_package(
                downloads / "update.zip",
                root,
                "kancolle-item-improvement-spider",
                {"VERSION": b"1.0.4\n", "app.txt": b"after\n"},
            )
            with self.assertRaises(RuntimeError):
                module._apply_action(root, ["--yes"], _config(base))
            self.assertEqual((root / "app.txt").read_text("utf-8"), "before\n")
            self.assertEqual(_git(root, "status", "--short"), "?? .flow/")

    def test_reapplying_same_version_target_identity_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            root, downloads = _init_project(base)
            sidecar = _write_package(
                downloads / "update.zip",
                root,
                "kancolle-item-improvement-spider",
                {"VERSION": b"1.0.4-rc.1\n", "app.txt": b"after\n"},
                from_version="1.0.4-rc.1",
                to_version="1.0.4-rc.1",
            )
            applied = module._apply_action(root, ["--yes"], _config(base))
            self.assertEqual(applied["status"], "成功")
            applied_root = downloads / ".flow-applied" / "kancolle-item-improvement-spider"
            archived_sidecar = next(applied_root.glob("*.flow.json"))
            archived_zip = applied_root / json.loads(archived_sidecar.read_text("utf-8"))["artifactFile"]
            archived_zip.replace(downloads / archived_zip.name)
            archived_sidecar.replace(downloads / archived_sidecar.name)

            repeated = module._apply_action(root, ["--yes"], _config(base))

            self.assertEqual(repeated["status"], "成功")
            self.assertIn("已是目标内容身份", repeated["current"] or repeated["status"] or "")
            self.assertEqual((root / "app.txt").read_text("utf-8"), "after\n")
            self.assertEqual(module._project_dirty_paths(root, _config(base)), [])

    def test_successful_update_can_be_rolled_back_and_reapplied(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            root, downloads = _init_project(base)
            sidecar = _write_package(
                downloads / "update.zip",
                root,
                "kancolle-item-improvement-spider",
                {"VERSION": b"1.0.4\n", "app.txt": b"after\n"},
            )
            applied = module._apply_action(root, ["--yes"], _config(base))
            self.assertEqual(applied["status"], "成功")
            self.assertEqual((root / "app.txt").read_text("utf-8"), "after\n")
            rolled = module._rollback_action(root, ["--yes"], _config(base))
            self.assertEqual(rolled["status"], "成功")
            self.assertEqual((root / "app.txt").read_text("utf-8"), "before\n")
            # Move the archived package back to the inbox and prove same-package reapply is possible.
            applied_root = downloads / ".flow-applied" / "kancolle-item-improvement-spider"
            archived_sidecar = next(applied_root.glob("*.flow.json"))
            archived_zip = applied_root / json.loads(archived_sidecar.read_text("utf-8"))["artifactFile"]
            new_zip = downloads / archived_zip.name
            new_sidecar = downloads / archived_sidecar.name
            archived_zip.replace(new_zip)
            archived_sidecar.replace(new_sidecar)
            reapplied = module._apply_action(root, ["--yes"], _config(base))
            self.assertEqual(reapplied["status"], "成功")
            self.assertEqual((root / "app.txt").read_text("utf-8"), "after\n")


    def test_rollback_does_not_execute_candidate_verifier(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            root, downloads = _init_project(base)
            _write_package(
                downloads / "update.zip",
                root,
                "kancolle-item-improvement-spider",
                {"VERSION": b"1.0.4\n", "app.txt": b"after\n"},
            )
            config = _config(base)
            module._apply_action(root, ["--yes"], config)
            config["update"]["candidateVerifier"] = ["{python}", "missing-candidate-verifier.py"]
            rolled = module._rollback_action(root, ["--yes"], config)
            self.assertEqual(rolled["status"], "成功")
            self.assertEqual((root / "app.txt").read_text("utf-8"), "before\n")

    def test_rollback_ignores_current_protected_generated_changes(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            root, downloads = _init_project(base)
            sidecar = _write_package(
                downloads / "update.zip",
                root,
                "kancolle-item-improvement-spider",
                {"VERSION": b"1.0.4\n", "app.txt": b"after\n"},
            )
            config = _config(base)
            config["update"]["protected"].append("generated/**")
            module._apply_action(root, ["--yes"], config)
            generated = root / "generated/state.json"
            generated.parent.mkdir(parents=True)
            generated.write_text("local generated state\n", encoding="utf-8")
            rolled = module._rollback_action(root, ["--yes"], config)
            self.assertEqual(rolled["status"], "成功")
            self.assertEqual((root / "app.txt").read_text("utf-8"), "before\n")
            self.assertEqual(generated.read_text("utf-8"), "local generated state\n")

    def test_migration_rollback_restores_original_commit_and_local_state(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            root, downloads = _init_project(base)
            (root / "local.txt").write_text("baseline\n", encoding="utf-8")
            _run_git(root, "add", "local.txt")
            _run_git(root, "commit", "-m", "local baseline")
            before_commit = _git(root, "rev-parse", "HEAD")

            # Local data existed before migration and must survive rollback.
            (root / "local.txt").write_text("local modified\n", encoding="utf-8")
            local_bytes = (root / "local.txt").read_bytes()
            (root / "VERSION").write_text("1.0.4-rc.3\n", encoding="utf-8")
            (root / "new-flow.txt").write_text("target\n", encoding="utf-8")
            _run_git(root, "add", "VERSION", "new-flow.txt")
            _run_git(root, "commit", "-m", "migration target")

            transaction = root / ".flow/state/transactions/migration-test"
            backup = transaction / "backup/files/local.txt"
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(local_bytes)
            metadata = {
                "schemaVersion": 1,
                "status": "applied",
                "rolledBack": False,
                "migration": True,
                "fromVersion": "1.0.4-rc.1",
                "toVersion": "1.0.4-rc.3",
                "before": {"commit": before_commit, "protectedDirtyPaths": ["local.txt"]},
                "paths": [{"path": "local.txt", "existed": True, "kind": "file", "sha256": _digest(local_bytes)}],
                "recoveryPackage": str(downloads / "recovery.zip"),
            }
            (transaction / "transaction.json").write_text(json.dumps(metadata), encoding="utf-8")

            rolled = module._rollback_action(root, ["--yes"], _config(base))
            self.assertEqual(rolled["status"], "成功")
            self.assertEqual(_git(root, "rev-parse", "HEAD"), before_commit)
            self.assertEqual((root / "VERSION").read_text("utf-8"), "1.0.4-rc.1\n")
            self.assertEqual((root / "local.txt").read_text("utf-8"), "local modified\n")
            self.assertFalse((root / ".flow").exists())
            self.assertTrue(any(downloads.glob("*migration-transaction-migration-test.zip")))

    def test_semver_selection_handles_double_digit_and_prerelease_order(self):
        self.assertGreater(module._version_key("1.0.10"), module._version_key("1.0.9"))
        self.assertGreater(module._version_key("1.0.4"), module._version_key("1.0.4-rc.10"))
        self.assertGreater(module._version_key("1.0.4-rc.10"), module._version_key("1.0.4-rc.2"))
        with self.assertRaises(module.UpdateError):
            module._version_key("v1.0")


if __name__ == "__main__":
    unittest.main()


class FlowContentUpdateTransactionTest(unittest.TestCase):
    def test_flow_content_update_writes_tracked_baseline_state(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            root, downloads = _init_project(base)
            (root / "configs").mkdir()
            (root / "configs/generated-state.json").write_text(
                json.dumps({
                    "schemaVersion": 1,
                    "id": "test-generated",
                    "role": "generated-state",
                    "backend": "git-ref",
                    "ref": "online",
                    "management": "project-managed",
                    "manifestPath": ".generated-state/manifest.json",
                    "exportPaths": ["generated"],
                    "baselineSyncPaths": ["generated"],
                    "forbiddenPaths": ["script", "tests", "configs", "VERSION"],
                    "excludePatterns": [],
                }),
                encoding="utf-8",
            )
            _run_git(root, "add", "configs/generated-state.json")
            _run_git(root, "commit", "-m", "add generated-state config")
            base_identity = flow_baseline.content_identity(root)
            files = {"VERSION": b"1.0.4\n", "app.txt": b"after\n"}
            original = {relative: (root / relative).read_bytes() for relative in files}
            try:
                for relative, content in files.items():
                    (root / relative).write_bytes(content)
                target_identity = flow_baseline.content_identity(root)
            finally:
                for relative, content in original.items():
                    (root / relative).write_bytes(content)
            changed = [{"path": k, "sha256": _digest(v), "mode": 0o644} for k, v in sorted(files.items())]
            manifest = {
                "schemaVersion": 2,
                "projectId": "kancolle-item-improvement-spider",
                "fromVersion": "1.0.4-rc.1",
                "toVersion": "1.0.4",
                "baseIdentity": base_identity,
                "targetIdentity": target_identity,
                "files": changed,
                "delete": [],
                "payloadHash": "sha256:" + flow_baseline.payload_hash(changed, []),
            }
            package = downloads / "flow-content.zip"
            with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("update-manifest.json", json.dumps(manifest))
                for relative, content in files.items():
                    archive.writestr(f"payload/{relative}", content)
            artifact.write_sidecar(
                package,
                package_type="update",
                package_id="test-flow-content",
                project_id="kancolle-item-improvement-spider",
                base_version="1.0.4-rc.1",
                target_version="1.0.4",
                base_identity=base_identity,
                target_identity=target_identity,
                schema_version=2,
            )
            config = _config(base)
            config["update"]["identityProvider"] = "script.project.ownership:identity_value"
            result = module._apply_action(root, ["--yes"], config)
            self.assertEqual(result["status"], "成功")
            baseline = json.loads((root / ".flow/baseline.json").read_text(encoding="utf-8"))
            self.assertEqual(baseline["contentIdentity"], target_identity)
            self.assertIn(".flow/baseline.json", _git(root, "show", "--pretty=", "--name-only", "HEAD"))
