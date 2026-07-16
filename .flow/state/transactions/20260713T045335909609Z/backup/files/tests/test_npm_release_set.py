from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from automation.release.npm_release_set import (
    ProjectCommandError,
    build_release_set,
    improvement2_version,
    verify_release_set,
)


ROOT = Path(__file__).resolve().parents[1]


def _release_package_fixture_available() -> bool:
    required = (
        ROOT / "dist" / "packages" / "kancolle-data" / "package.json",
        ROOT / "dist" / "packages" / "kancolle-data" / "manifest.json",
        ROOT / "dist" / "packages" / "kancolle-data" / "improvement" / "detail.nedb",
        ROOT / "dist" / "packages" / "kancolle-data" / "equipment" / "sources.nedb",
        ROOT
        / "dist"
        / "packages"
        / "kancolle-data"
        / "compat"
        / "poi-plugin-item-improvement2"
        / "manifest.json",
        ROOT
        / "dist"
        / "packages"
        / "kancolle-data"
        / "compat"
        / "poi-plugin-item-improvement2"
        / "improvement"
        / "detail.nedb",
    )
    return all(path.is_file() for path in required)



def _write_release_tarball(
    path: Path,
    *,
    version: str,
    canonical_version: str,
    schema_version: int,
    content_digest: str,
    compatibility: bool,
) -> None:
    with tempfile.TemporaryDirectory() as temp_name:
        root = Path(temp_name) / "package"
        (root / "improvement").mkdir(parents=True)
        (root / "package.json").write_text(
            json.dumps({"name": "@sakura2333/kancolle-data", "version": version}),
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
        (root / "RELEASES.json").write_text(
            json.dumps(
                [{"version": canonical_version, "contentDigest": content_digest}]
            ),
            encoding="utf-8",
        )
        if compatibility:
            (root / "improvement" / "detail.nedb").write_text(
                json.dumps({"id": 1, "name": "fixture", "improvementList": []}) + "\n",
                encoding="utf-8",
            )
        with tarfile.open(path, "w:gz") as archive:
            archive.add(root, arcname="package")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


class NpmReleaseSetTest(unittest.TestCase):
    def test_improvement2_version_is_deterministic_and_unique(self):
        self.assertEqual(improvement2_version("0.5.1"), "0.5.1-improvement2")
        self.assertEqual(
            improvement2_version("0.5.1-beta.2"),
            "0.5.1-beta.2.improvement2",
        )

    def test_release_set_requires_both_variants_to_share_consumer_digest(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            canonical = root / "canonical.tgz"
            compatibility = root / "compatibility.tgz"
            canonical_version = "0.5.10"
            compatibility_version = improvement2_version(canonical_version)
            _write_release_tarball(
                canonical,
                version=canonical_version,
                canonical_version=canonical_version,
                schema_version=4,
                content_digest="a" * 64,
                compatibility=False,
            )
            _write_release_tarball(
                compatibility,
                version=compatibility_version,
                canonical_version=canonical_version,
                schema_version=3,
                content_digest="b" * 64,
                compatibility=True,
            )
            payload = {
                "schemaVersion": 1,
                "package": "@sakura2333/kancolle-data",
                "policy": "frozen-build-candidate-with-improvement2-projection",
                "publishMode": "idempotent-release-action",
                "artifacts": [
                    {
                        "variant": "current",
                        "consumer": None,
                        "distTag": "latest",
                        "package": "@sakura2333/kancolle-data",
                        "version": canonical_version,
                        "tarball": canonical.name,
                        "sha256": _sha256(canonical),
                        "contentDigest": "a" * 64,
                    },
                    {
                        "variant": "improvement2",
                        "consumer": "poi-plugin-item-improvement2",
                        "distTag": "improvement2",
                        "package": "@sakura2333/kancolle-data",
                        "version": compatibility_version,
                        "tarball": compatibility.name,
                        "sha256": _sha256(compatibility),
                        "contentDigest": "b" * 64,
                    },
                ],
            }
            manifest = root / "release-set.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                ProjectCommandError,
                "different consumer contentDigest",
            ):
                verify_release_set(manifest)

    def test_release_set_accepts_matching_variant_consumer_digests(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            canonical = root / "canonical.tgz"
            compatibility = root / "compatibility.tgz"
            canonical_version = "0.5.10"
            compatibility_version = improvement2_version(canonical_version)
            digest = "a" * 64
            _write_release_tarball(
                canonical,
                version=canonical_version,
                canonical_version=canonical_version,
                schema_version=4,
                content_digest=digest,
                compatibility=False,
            )
            _write_release_tarball(
                compatibility,
                version=compatibility_version,
                canonical_version=canonical_version,
                schema_version=3,
                content_digest=digest,
                compatibility=True,
            )
            payload = {
                "schemaVersion": 1,
                "package": "@sakura2333/kancolle-data",
                "policy": "frozen-build-candidate-with-improvement2-projection",
                "publishMode": "idempotent-release-action",
                "artifacts": [
                    {
                        "variant": "current",
                        "consumer": None,
                        "distTag": "latest",
                        "package": "@sakura2333/kancolle-data",
                        "version": canonical_version,
                        "tarball": canonical.name,
                        "sha256": _sha256(canonical),
                        "contentDigest": digest,
                    },
                    {
                        "variant": "improvement2",
                        "consumer": "poi-plugin-item-improvement2",
                        "distTag": "improvement2",
                        "package": "@sakura2333/kancolle-data",
                        "version": compatibility_version,
                        "tarball": compatibility.name,
                        "sha256": _sha256(compatibility),
                        "contentDigest": digest,
                    },
                ],
            }
            manifest = root / "release-set.json"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            verified = verify_release_set(manifest)
            self.assertEqual(
                [item["contentDigest"] for item in verified["artifacts"]],
                [digest, digest],
            )

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

            current, compatibility = verified["artifacts"]
            self.assertEqual(current["version"], "0.5.1")
            self.assertEqual(compatibility["version"], "0.5.1-improvement2")

            with tarfile.open(output / compatibility["tarball"], "r:gz") as archive:
                manifest_stream = archive.extractfile("package/manifest.json")
                self.assertIsNotNone(manifest_stream)
                manifest = json.loads(manifest_stream.read().decode("utf-8"))
                self.assertEqual(manifest["datasets"]["improvement"]["schemaVersion"], 3)
                self.assertNotIn("compatibility", manifest)
                self.assertNotIn("package/compat/poi-plugin-item-improvement2/manifest.json", archive.getnames())

                detail_stream = archive.extractfile("package/improvement/detail.nedb")
                self.assertIsNotNone(detail_stream)
                first = json.loads(detail_stream.readline().decode("utf-8"))
                self.assertEqual(set(first), {"id", "name", "improvementList"})
                self.assertNotIn("stepList", first["improvementList"][0])

            with tarfile.open(output / current["tarball"], "r:gz") as archive:
                names = set(archive.getnames())
                self.assertNotIn("package/compat/poi-plugin-item-improvement2/manifest.json", names)
                manifest_stream = archive.extractfile("package/manifest.json")
                self.assertIsNotNone(manifest_stream)
                manifest = json.loads(manifest_stream.read().decode("utf-8"))
                self.assertEqual(manifest["datasets"]["improvement"]["schemaVersion"], 4)


if __name__ == "__main__":
    unittest.main()
