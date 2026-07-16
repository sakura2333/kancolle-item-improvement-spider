from __future__ import annotations

import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
import sys

SCRIPT_PROJECT = Path(__file__).resolve().parents[1] / "script" / "project"
if str(SCRIPT_PROJECT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PROJECT))

import _npm_registry as npm_publish


class FakeNpm:
    def __init__(
        self,
        tarball: Path,
        *,
        remote: str = "missing",
        publish_returncode: int = 0,
        tags: dict[str, str] | None = None,
    ):
        self.tarball = tarball
        self.remote = remote
        self.publish_returncode = publish_returncode
        self.tags = dict(tags or ({"latest": "1.0.0"} if remote != "missing" else {}))
        self.calls: list[list[str]] = []

    def __call__(self, command):
        command = [str(item) for item in command]
        self.calls.append(command)
        if command[:4] == ["npm", "config", "get", "registry"]:
            return subprocess.CompletedProcess(command, 0, "https://registry.npmjs.org/\n", "")
        if command[:2] == ["npm", "publish"]:
            self.remote = "same"
            tag = command[command.index("--tag") + 1]
            self.tags[tag] = "1.0.0"
            return subprocess.CompletedProcess(
                command,
                self.publish_returncode,
                "+ @test/data@1.0.0\n" if self.publish_returncode == 0 else "",
                "network timeout" if self.publish_returncode else "",
            )
        if command[:3] == ["npm", "dist-tag", "add"]:
            spec = command[3]
            tag = command[4]
            self.tags[tag] = spec.rsplit("@", 1)[1]
            return subprocess.CompletedProcess(command, 0, "+latest\n", "")
        if command[:2] == ["npm", "view"] and command[3] == "dist-tags":
            return subprocess.CompletedProcess(command, 0, json.dumps(self.tags), "")
        if command[:2] == ["npm", "view"] and command[3] == "dist":
            if self.remote == "missing":
                return subprocess.CompletedProcess(command, 1, "", "npm error code E404")
            if self.remote == "same":
                payload = {
                    "shasum": npm_publish._digest(self.tarball, "sha1"),
                    "integrity": npm_publish._integrity_sha512(self.tarball),
                    "tarball": "https://registry.example/test.tgz",
                }
            else:
                payload = {
                    "shasum": "0" * 40,
                    "integrity": "sha512-invalid",
                    "tarball": "https://registry.example/test.tgz",
                }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        raise AssertionError(command)


def _package_fixture(root: Path) -> tuple[Path, Path]:
    source = root / "package"
    source.mkdir()
    (source / "package.json").write_text(
        json.dumps({"name": "@test/data", "version": "1.0.0"}), encoding="utf-8"
    )
    (source / "data.json").write_text('{"ok":true}\n', encoding="utf-8")
    tarball = root / "test-data-1.0.0.tgz"
    with tarfile.open(tarball, "w:gz") as archive:
        archive.add(source / "package.json", arcname="package/package.json")
        archive.add(source / "data.json", arcname="package/data.json")
    result = root / "package-result.json"
    result.write_text(
        json.dumps(
            {
                "schema": 1,
                "package": "@test/data",
                "version": "1.0.0",
                "tarball": str(tarball),
                "sha256": npm_publish._digest(tarball, "sha256"),
            }
        ),
        encoding="utf-8",
    )
    return tarball, result


class NpmPublishReconciliationTest(unittest.TestCase):
    def test_query_only_does_not_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tarball, result = _package_fixture(root)
            runner = FakeNpm(tarball)
            audit = npm_publish.reconcile_npm_publish(
                package_result_path=result,
                audit_output=root / "audit.json",
                tag="latest",
                publish=False,
                runner=runner,
            )
            self.assertEqual(audit["status"], "ready-not-published")
            self.assertFalse(any(call[:2] == ["npm", "publish"] for call in runner.calls))

    def test_publish_then_confirm_same_tarball_and_tag(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tarball, result = _package_fixture(root)
            runner = FakeNpm(tarball)
            audit = npm_publish.reconcile_npm_publish(
                package_result_path=result,
                audit_output=root / "audit.json",
                tag="latest",
                publish=True,
                retries=1,
                retry_delay=0,
                runner=runner,
            )
            self.assertEqual(audit["status"], "published")
            self.assertTrue(audit["comparison"]["matches"])
            self.assertEqual(audit["distTag"]["after"], "1.0.0")

    def test_timeout_after_registry_acceptance_is_reconciled(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tarball, result = _package_fixture(root)
            runner = FakeNpm(tarball, publish_returncode=1)
            audit = npm_publish.reconcile_npm_publish(
                package_result_path=result,
                audit_output=root / "audit.json",
                tag="latest",
                publish=True,
                retries=1,
                retry_delay=0,
                runner=runner,
            )
            self.assertEqual(audit["status"], "published-reconciled-after-command-error")
            self.assertEqual(audit["publishAttempt"]["returnCode"], 1)

    def test_existing_same_tarball_is_idempotent_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tarball, result = _package_fixture(root)
            runner = FakeNpm(tarball, remote="same")
            audit = npm_publish.reconcile_npm_publish(
                package_result_path=result,
                audit_output=root / "audit.json",
                tag="latest",
                publish=True,
                runner=runner,
            )
            self.assertEqual(audit["status"], "already-published")
            self.assertFalse(any(call[:2] == ["npm", "publish"] for call in runner.calls))

    def test_existing_same_tarball_can_reconcile_missing_tag(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tarball, result = _package_fixture(root)
            runner = FakeNpm(tarball, remote="same", tags={})
            audit = npm_publish.reconcile_npm_publish(
                package_result_path=result,
                audit_output=root / "audit.json",
                tag="beta",
                publish=True,
                runner=runner,
            )
            self.assertEqual(audit["status"], "tag-reconciled")
            self.assertEqual(runner.tags["beta"], "1.0.0")

    def test_existing_different_tarball_is_hard_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tarball, result = _package_fixture(root)
            runner = FakeNpm(tarball, remote="different")
            audit_path = root / "audit.json"
            with self.assertRaisesRegex(npm_publish.NpmPublishError, "different tarball"):
                npm_publish.reconcile_npm_publish(
                    package_result_path=result,
                    audit_output=audit_path,
                    tag="latest",
                    publish=True,
                    runner=runner,
                )
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertEqual(audit["status"], "immutable-version-conflict")


if __name__ == "__main__":
    unittest.main()
