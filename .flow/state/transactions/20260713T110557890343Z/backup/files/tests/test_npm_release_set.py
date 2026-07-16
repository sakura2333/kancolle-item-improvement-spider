from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

from automation.release.consumer_identity import (
    CURRENT_VARIANT,
    IMPROVEMENT2_VARIANT,
    inspect_directory,
)
from automation.release.npm_business_identity import (
    IDENTITY_SCHEMA_VERSION as NPM_BUSINESS_IDENTITY_SCHEMA_VERSION,
    inspect_tarball as inspect_npm_business_tarball,
)
from automation.release.npm_release_set import (
    ProjectCommandError,
    build_release_set,
    hydrate_published_artifacts,
    improvement2_version,
    verify_release_set,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "@sakura2333/kancolle-data"


def _release_package_fixture_available() -> bool:
    required = (
        ROOT / "dist/packages/kancolle-data/package.json",
        ROOT / "dist/packages/kancolle-data/manifest.json",
        ROOT / "dist/packages/kancolle-data/improvement/detail.nedb",
        ROOT / "dist/packages/kancolle-data/equipment/sources.nedb",
        ROOT / "dist/packages/kancolle-data/compat/poi-plugin-item-improvement2/manifest.json",
        ROOT / "dist/packages/kancolle-data/compat/poi-plugin-item-improvement2/improvement/detail.nedb",
    )
    return all(path.is_file() for path in required)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_release_tarball(
    path: Path,
    *,
    version: str,
    canonical_version: str,
    schema_version: int,
    compatibility: bool,
    seed: str,
    declared_digest: str | None = None,
) -> str:
    with tempfile.TemporaryDirectory() as temp_name:
        root = Path(temp_name) / "package"
        for relative in (
            "improvement",
            "equipment",
            "assets/equip",
            "assets/useitem",
        ):
            (root / relative).mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(
            json.dumps({"name": PACKAGE_NAME, "version": version}),
            encoding="utf-8",
        )
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "packageVersion": version,
                    "datasets": {"improvement": {"schemaVersion": schema_version}},
                }
            ),
            encoding="utf-8",
        )
        (root / "improvement/list.json").write_text(
            json.dumps({"data": [[{"id": 1, "seed": seed}]]}),
            encoding="utf-8",
        )
        if compatibility:
            detail = {"id": 1, "name": f"fixture-{seed}", "improvementList": []}
            variant = IMPROVEMENT2_VARIANT
        else:
            detail = {
                "id": 1,
                "name": f"fixture-{seed}",
                "improvementList": [{"stepList": [], "seed": seed}],
            }
            variant = CURRENT_VARIANT
        (root / "improvement/detail.nedb").write_text(
            json.dumps(detail, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        for filename in ("drop-from.nedb", "sources.nedb", "special-bonuses.nedb"):
            (root / "equipment" / filename).write_text(
                json.dumps({"id": 1, "seed": seed}) + "\n",
                encoding="utf-8",
            )
        (root / "assets/equip/1.png").write_bytes(("equip-" + seed).encode())
        (root / "assets/useitem/1.png").write_bytes(("useitem-" + seed).encode())

        identity = inspect_directory(root, variant=variant)
        release_entry = {
            "version": canonical_version,
            "contentDigest": None,
            "improvement2ContentDigest": None,
            "identitySchemaVersion": identity["schemaVersion"],
        }
        key = "improvement2ContentDigest" if compatibility else "contentDigest"
        release_entry[key] = declared_digest or identity["contentDigest"]
        (root / "RELEASES.json").write_text(
            json.dumps([release_entry]),
            encoding="utf-8",
        )
        with tarfile.open(path, "w:gz") as archive:
            archive.add(root, arcname="package")
        return str(identity["contentDigest"])


def _release_set_payload(
    root: Path,
    *,
    canonical: Path,
    compatibility: Path,
    canonical_digest: str,
    compatibility_digest: str,
) -> dict:
    canonical_version = "0.5.10"
    compatibility_version = improvement2_version(canonical_version)
    canonical_business_digest = str(
        inspect_npm_business_tarball(canonical)["businessDigest"]
    )
    compatibility_business_digest = str(
        inspect_npm_business_tarball(compatibility)["businessDigest"]
    )
    artifacts = []
    for variant, consumer, tag, version, tarball, digest, result_name in (
        (
            CURRENT_VARIANT,
            None,
            "latest",
            canonical_version,
            canonical,
            canonical_digest,
            "current.package-result.json",
        ),
        (
            IMPROVEMENT2_VARIANT,
            "poi-plugin-item-improvement2",
            "improvement2",
            compatibility_version,
            compatibility,
            compatibility_digest,
            "improvement2.package-result.json",
        ),
    ):
        business_digest = (
            canonical_business_digest
            if variant == CURRENT_VARIANT
            else compatibility_business_digest
        )
        result = {
            "schema": 1,
            "package": PACKAGE_NAME,
            "version": version,
            "tarball": tarball.name,
            "filename": tarball.name,
            "sha256": _sha256(tarball),
            "bytes": tarball.stat().st_size,
            "contentDigest": digest,
            "businessDigest": business_digest,
        }
        (root / result_name).write_text(json.dumps(result), encoding="utf-8")
        artifacts.append(
            {
                "variant": variant,
                "consumer": consumer,
                "distTag": tag,
                "packageResult": result_name,
                **result,
            }
        )
    return {
        "schemaVersion": 1,
        "package": PACKAGE_NAME,
        "policy": "frozen-build-candidate-with-improvement2-projection",
        "publishMode": "idempotent-release-action",
        "consumerIdentities": {
            "schemaVersion": 2,
            "current": canonical_digest,
            "improvement2": compatibility_digest,
        },
        "npmBusinessIdentities": {
            "schemaVersion": NPM_BUSINESS_IDENTITY_SCHEMA_VERSION,
            "current": canonical_business_digest,
            "improvement2": compatibility_business_digest,
        },
        "artifacts": artifacts,
    }


def _write_hydration_fixture(
    root: Path,
    *,
    registry_compatibility_seed: str,
) -> tuple[Path, Path, dict[str, Path], tuple[str, str]]:
    canonical_version = "0.5.10"
    compatibility_version = improvement2_version(canonical_version)
    local_current = root / "local-current.tgz"
    local_compatibility = root / "local-improvement2.tgz"
    registry_current = root / "registry-current.tgz"
    registry_compatibility = root / "registry-improvement2.tgz"

    canonical_digest = _write_release_tarball(
        local_current,
        version=canonical_version,
        canonical_version=canonical_version,
        schema_version=4,
        compatibility=False,
        seed="same",
    )
    compatibility_digest = _write_release_tarball(
        local_compatibility,
        version=compatibility_version,
        canonical_version=canonical_version,
        schema_version=3,
        compatibility=True,
        seed="same",
    )
    _write_release_tarball(
        registry_current,
        version=canonical_version,
        canonical_version=canonical_version,
        schema_version=4,
        compatibility=False,
        seed="same",
    )
    _write_release_tarball(
        registry_compatibility,
        version=compatibility_version,
        canonical_version=canonical_version,
        schema_version=3,
        compatibility=True,
        seed=registry_compatibility_seed,
    )

    manifest = root / "release-set.json"
    manifest.write_text(
        json.dumps(
            _release_set_payload(
                root,
                canonical=local_current,
                compatibility=local_compatibility,
                canonical_digest=canonical_digest,
                compatibility_digest=compatibility_digest,
            )
        ),
        encoding="utf-8",
    )
    versions = root / "published-versions.json"
    versions.write_text(
        json.dumps([canonical_version, compatibility_version]),
        encoding="utf-8",
    )
    registry = {
        canonical_version: registry_current,
        compatibility_version: registry_compatibility,
    }
    return manifest, versions, registry, (canonical_digest, compatibility_digest)


class NpmReleaseSetTest(unittest.TestCase):
    def test_improvement2_version_is_deterministic_and_unique(self):
        self.assertEqual(improvement2_version("0.5.1"), "0.5.1-improvement2")
        self.assertEqual(
            improvement2_version("0.5.1-beta.2"),
            "0.5.1-beta.2.improvement2",
        )

    def test_release_set_verifies_independent_canonical_and_projection_identities(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            canonical = root / "canonical.tgz"
            compatibility = root / "compatibility.tgz"
            canonical_digest = _write_release_tarball(
                canonical,
                version="0.5.10",
                canonical_version="0.5.10",
                schema_version=4,
                compatibility=False,
                seed="same",
            )
            compatibility_digest = _write_release_tarball(
                compatibility,
                version="0.5.10-improvement2",
                canonical_version="0.5.10",
                schema_version=3,
                compatibility=True,
                seed="same",
            )
            self.assertNotEqual(canonical_digest, compatibility_digest)
            manifest = root / "release-set.json"
            manifest.write_text(
                json.dumps(
                    _release_set_payload(
                        root,
                        canonical=canonical,
                        compatibility=compatibility,
                        canonical_digest=canonical_digest,
                        compatibility_digest=compatibility_digest,
                    )
                ),
                encoding="utf-8",
            )
            verified = verify_release_set(manifest)
            self.assertEqual(
                verified["consumerIdentities"],
                {
                    "schemaVersion": 2,
                    "current": canonical_digest,
                    "improvement2": compatibility_digest,
                },
            )
            self.assertEqual(
                verified["npmBusinessIdentities"],
                {
                    "schemaVersion": NPM_BUSINESS_IDENTITY_SCHEMA_VERSION,
                    "current": inspect_npm_business_tarball(canonical)["businessDigest"],
                    "improvement2": inspect_npm_business_tarball(compatibility)["businessDigest"],
                },
            )

    def test_release_set_rejects_identity_metadata_that_does_not_match_files(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            canonical = root / "canonical.tgz"
            compatibility = root / "compatibility.tgz"
            canonical_digest = _write_release_tarball(
                canonical,
                version="0.5.10",
                canonical_version="0.5.10",
                schema_version=4,
                compatibility=False,
                seed="same",
            )
            compatibility_digest = _write_release_tarball(
                compatibility,
                version="0.5.10-improvement2",
                canonical_version="0.5.10",
                schema_version=3,
                compatibility=True,
                seed="same",
            )
            payload = _release_set_payload(
                root,
                canonical=canonical,
                compatibility=compatibility,
                canonical_digest=canonical_digest,
                compatibility_digest=compatibility_digest,
            )
            payload["consumerIdentities"]["improvement2"] = "f" * 64
            manifest = root / "release-set.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ProjectCommandError, "consumer identity mismatch"):
                verify_release_set(manifest)

    def test_release_set_ignores_legacy_self_reported_digest_and_recomputes_tarball(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            canonical = root / "canonical.tgz"
            compatibility = root / "compatibility.tgz"
            canonical_digest = _write_release_tarball(
                canonical,
                version="0.5.10",
                canonical_version="0.5.10",
                schema_version=4,
                compatibility=False,
                seed="same",
                declared_digest="0" * 64,
            )
            compatibility_digest = _write_release_tarball(
                compatibility,
                version="0.5.10-improvement2",
                canonical_version="0.5.10",
                schema_version=3,
                compatibility=True,
                seed="same",
                declared_digest="f" * 64,
            )
            manifest = root / "release-set.json"
            manifest.write_text(
                json.dumps(
                    _release_set_payload(
                        root,
                        canonical=canonical,
                        compatibility=compatibility,
                        canonical_digest=canonical_digest,
                        compatibility_digest=compatibility_digest,
                    )
                ),
                encoding="utf-8",
            )
            verified = verify_release_set(manifest)
            self.assertEqual(
                verified["consumerIdentities"]["current"], canonical_digest
            )
            self.assertEqual(
                verified["consumerIdentities"]["improvement2"], compatibility_digest
            )

    def test_hydrate_published_artifacts_uses_registry_bytes_and_reverifies(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            manifest, versions, registry, digests = _write_hydration_fixture(
                root,
                registry_compatibility_seed="same",
            )

            def fake_run(command, **kwargs):
                version = str(command[2]).rsplit("@", 1)[1]
                destination = Path(command[command.index("--pack-destination") + 1])
                source = registry[version]
                target = destination / source.name
                shutil.copy2(source, target)
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps([{"filename": target.name}]),
                    stderr="",
                )

            with mock.patch(
                "automation.release.npm_release_set.subprocess.run",
                side_effect=fake_run,
            ):
                verified = hydrate_published_artifacts(manifest, versions)

            self.assertEqual(
                [item["tarball"] for item in verified["artifacts"]],
                ["registry-current.tgz", "registry-improvement2.tgz"],
            )
            self.assertEqual(
                [item["contentDigest"] for item in verified["artifacts"]],
                list(digests),
            )

    def test_hydrate_published_artifacts_rejects_actual_registry_identity_conflict(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            manifest, versions, registry, _ = _write_hydration_fixture(
                root,
                registry_compatibility_seed="different",
            )

            def fake_run(command, **kwargs):
                version = str(command[2]).rsplit("@", 1)[1]
                destination = Path(command[command.index("--pack-destination") + 1])
                source = registry[version]
                target = destination / source.name
                shutil.copy2(source, target)
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps([{"filename": target.name}]),
                    stderr="",
                )

            with mock.patch(
                "automation.release.npm_release_set.subprocess.run",
                side_effect=fake_run,
            ):
                with self.assertRaisesRegex(ProjectCommandError, "immutable npm registry conflict"):
                    hydrate_published_artifacts(manifest, versions)

    def test_stable_release_set_builds_current_and_legacy_default_paths(self):
        if not _release_package_fixture_available():
            self.skipTest("npm release-set integration requires generated package datasets")
        with tempfile.TemporaryDirectory() as temp_name:
            output = Path(temp_name) / "npm"
            release_set = build_release_set(ROOT, output, require_fresh=False)
            verified = verify_release_set(output / "release-set.json")

            self.assertEqual(release_set["publishMode"], "idempotent-release-action")
            self.assertEqual(
                [(item["variant"], item["distTag"]) for item in verified["artifacts"]],
                [("current", "latest"), ("improvement2", "improvement2")],
            )
            self.assertNotEqual(
                verified["consumerIdentities"]["current"],
                verified["consumerIdentities"]["improvement2"],
            )
            self.assertNotEqual(
                verified["npmBusinessIdentities"]["current"],
                verified["npmBusinessIdentities"]["improvement2"],
            )

            current, compatibility = verified["artifacts"]
            self.assertEqual(current["version"], "0.5.1")
            self.assertEqual(compatibility["version"], "0.5.1-improvement2")

            with tarfile.open(output / compatibility["tarball"], "r:gz") as archive:
                manifest_stream = archive.extractfile("package/manifest.json")
                self.assertIsNotNone(manifest_stream)
                manifest = json.loads(manifest_stream.read().decode("utf-8"))
                self.assertEqual(manifest["datasets"]["improvement"]["schemaVersion"], 3)
                self.assertNotIn("compatibility", manifest)
                self.assertNotIn(
                    "package/compat/poi-plugin-item-improvement2/manifest.json",
                    archive.getnames(),
                )

                detail_stream = archive.extractfile("package/improvement/detail.nedb")
                self.assertIsNotNone(detail_stream)
                first = json.loads(detail_stream.readline().decode("utf-8"))
                self.assertEqual(set(first), {"id", "name", "improvementList"})
                self.assertNotIn("stepList", first["improvementList"][0])

            with tarfile.open(output / current["tarball"], "r:gz") as archive:
                names = set(archive.getnames())
                self.assertNotIn(
                    "package/compat/poi-plugin-item-improvement2/manifest.json",
                    names,
                )
                manifest_stream = archive.extractfile("package/manifest.json")
                self.assertIsNotNone(manifest_stream)
                manifest = json.loads(manifest_stream.read().decode("utf-8"))
                self.assertEqual(manifest["datasets"]["improvement"]["schemaVersion"], 4)


if __name__ == "__main__":
    unittest.main()
