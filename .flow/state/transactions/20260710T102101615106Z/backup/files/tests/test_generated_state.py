from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from service.generated_state.artifact import (
    create_generated_state_artifact,
    verify_generated_state_artifact,
)
from service.generated_state.config import GeneratedStateConfig, GeneratedStateConfigError
from service.generated_state.manifest import (
    GeneratedStateError,
    export_generated_state,
    verify_generated_state,
)
from service.generated_state.sync import (
    apply_generated_baseline,
    build_sync_report,
    restore_generated_baseline,
)


def _config() -> GeneratedStateConfig:
    config = GeneratedStateConfig(
        schema_version=1,
        state_id="test-state",
        role="generated-state",
        backend="git-ref",
        ref="online",
        management="project-managed",
        manifest_path=".generated-state/manifest.json",
        export_paths=("dist/data-pipeline/improvement", "dist/packages/kancolle-data"),
        baseline_sync_paths=(
            "dist/data-pipeline/improvement",
            "dist/packages/kancolle-data/manifest.json",
        ),
        forbidden_paths=("service", "script", "tests"),
        exclude_patterns=("**/node_modules/**", "**/*.tgz"),
    )
    config.validate()
    return config


def _project(root: Path, *, value: str) -> None:
    (root / "dist/data-pipeline/improvement").mkdir(parents=True)
    (root / "dist/data-pipeline/improvement/value.json").write_text(
        json.dumps({"value": value}), encoding="utf-8"
    )
    package_source = root / "packages/kancolle-data"
    package_source.mkdir(parents=True)
    (package_source / "package.json").write_text(
        json.dumps({"name": "@test/data", "version": "1.0.0"}), encoding="utf-8"
    )
    package = root / "dist/packages/kancolle-data"
    package.mkdir(parents=True)
    (package / "package.json").write_text(
        json.dumps({"name": "@test/data", "version": "1.0.0"}), encoding="utf-8"
    )
    (package / "manifest.json").write_text(
        json.dumps({"packageVersion": "1.0.0", "generatedAt": "2026-06-29T00:00:00Z", "datasets": {}}),
        encoding="utf-8",
    )
    (package / "node_modules/ignored").mkdir(parents=True)
    (package / "node_modules/ignored/file.js").write_text("ignored", encoding="utf-8")
    (package / "ignored.tgz").write_bytes(b"ignored")
    (root / "VERSION").write_text("0.1.4\n", encoding="utf-8")


class GeneratedStateTest(unittest.TestCase):
    def test_config_rejects_forbidden_baseline_path(self):
        config = GeneratedStateConfig(
            schema_version=1,
            state_id="bad",
            role="generated-state",
            backend="git-ref",
            ref="online",
            management="project-managed",
            manifest_path=".generated-state/manifest.json",
            export_paths=("service",),
            baseline_sync_paths=("service",),
            forbidden_paths=("service",),
            exclude_patterns=(),
        )
        with self.assertRaises(GeneratedStateConfigError):
            config.validate()

    def test_export_verify_and_detect_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            state = root / "state"
            _project(project, value="new")
            result = export_generated_state(
                project_root=project,
                output_dir=state,
                base_ref="main",
                base_commit="a" * 40,
                config=_config(),
            )
            self.assertEqual(result["baseCommit"], "a" * 40)
            verified = verify_generated_state(state, _config())
            self.assertEqual(verified["outputCount"], 3)
            self.assertFalse((state / "packages/kancolle-data/node_modules").exists())
            self.assertFalse((state / "packages/kancolle-data/ignored.tgz").exists())
            (state / "dist/data-pipeline/improvement/value.json").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(GeneratedStateError, "mismatch"):
                verify_generated_state(state, _config())


    def test_export_rejects_project_ancestor_as_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            _project(project, value="new")
            with self.assertRaisesRegex(GeneratedStateError, "ancestors"):
                export_generated_state(
                    project_root=project,
                    output_dir=root,
                    base_ref="main",
                    base_commit="c" * 40,
                    config=_config(),
                    replace=True,
                )
            self.assertTrue((project / "VERSION").is_file())

    def test_apply_no_changes_creates_no_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            state = root / "state"
            backup = root / "backup"
            _project(project, value="same")
            export_generated_state(
                project_root=project,
                output_dir=state,
                base_ref="main",
                base_commit="d" * 40,
                config=_config(),
            )
            result = apply_generated_baseline(
                state_root=state,
                project_root=project,
                backup_dir=backup,
                config=_config(),
            )
            self.assertFalse(result["applied"])
            self.assertIsNone(result["backupDir"])
            self.assertFalse(backup.exists())

    def test_sync_is_explicit_and_recoverable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_project = root / "source"
            target_project = root / "target"
            state = root / "state"
            backup = root / "backup"
            _project(source_project, value="new")
            _project(target_project, value="old")
            export_generated_state(
                project_root=source_project,
                output_dir=state,
                base_ref="main",
                base_commit="b" * 40,
                config=_config(),
            )
            report = build_sync_report(
                state_root=state,
                project_root=target_project,
                config=_config(),
            )
            self.assertTrue(report["hasChanges"])
            self.assertIn("dist/data-pipeline/improvement/value.json", report["changes"]["modified"])

            applied = apply_generated_baseline(
                state_root=state,
                project_root=target_project,
                backup_dir=backup,
                config=_config(),
            )
            self.assertEqual(
                json.loads((target_project / "dist/data-pipeline/improvement/value.json").read_text())["value"],
                "new",
            )
            restore_generated_baseline(
                project_root=target_project,
                backup_dir=backup,
                paths=applied["paths"],
                originally_present=applied["originallyPresent"],
            )
            self.assertEqual(
                json.loads((target_project / "dist/data-pipeline/improvement/value.json").read_text())["value"],
                "old",
            )


    def test_artifact_is_deterministic_and_receipt_is_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            state = root / "state"
            first = root / "first.zip"
            second = root / "second.zip"
            receipt = root / "first.receipt.json"
            _project(project, value="new")
            export_generated_state(
                project_root=project,
                output_dir=state,
                base_ref="main",
                base_commit="e" * 40,
                config=_config(),
                build_id="build-1",
            )
            created = create_generated_state_artifact(
                state_root=state,
                output_file=first,
                receipt_file=receipt,
                config=_config(),
            )
            create_generated_state_artifact(
                state_root=state,
                output_file=second,
                config=_config(),
            )
            self.assertEqual(first.read_bytes(), second.read_bytes())
            verified = verify_generated_state_artifact(
                archive_file=first,
                receipt_file=receipt,
                config=_config(),
            )
            self.assertEqual(verified["buildId"], "build-1")
            self.assertTrue(verified["receiptVerified"])
            self.assertEqual(created["artifact"]["sha256"], verified["artifactSha256"])

    def test_artifact_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as target:
                target.writestr("../escape.json", "{}")
            with self.assertRaisesRegex(GeneratedStateError, "unsafe"):
                verify_generated_state_artifact(
                    archive_file=archive,
                    config=_config(),
                )

    def test_artifact_receipt_detects_archive_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            state = root / "state"
            archive = root / "state.zip"
            receipt = root / "state.receipt.json"
            _project(project, value="new")
            export_generated_state(
                project_root=project,
                output_dir=state,
                base_ref="main",
                base_commit="f" * 40,
                config=_config(),
            )
            create_generated_state_artifact(
                state_root=state,
                output_file=archive,
                receipt_file=receipt,
                config=_config(),
            )
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            payload["artifact"]["sha256"] = "0" * 64
            receipt.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(GeneratedStateError, "sha256"):
                verify_generated_state_artifact(
                    archive_file=archive,
                    receipt_file=receipt,
                    config=_config(),
                )


if __name__ == "__main__":
    unittest.main()
