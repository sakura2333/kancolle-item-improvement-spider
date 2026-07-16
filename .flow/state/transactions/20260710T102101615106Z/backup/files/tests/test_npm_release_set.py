from __future__ import annotations

import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from script.project.npm_release_set import (
    build_release_set,
    improvement2_version,
    verify_release_set,
)


ROOT = Path(__file__).resolve().parents[1]


def _release_package_fixture_available() -> bool:
    required = (
        ROOT / "packages" / "kancolle-data" / "package.json",
        ROOT / "packages" / "kancolle-data" / "manifest.json",
        ROOT / "packages" / "kancolle-data" / "improvement" / "detail.nedb",
        ROOT / "packages" / "kancolle-data" / "equipment" / "sources.nedb",
    )
    return all(path.is_file() for path in required)


class NpmReleaseSetTest(unittest.TestCase):
    def test_improvement2_version_is_deterministic_and_unique(self):
        self.assertEqual(improvement2_version("0.5.1"), "0.5.1-improvement2")
        self.assertEqual(
            improvement2_version("0.5.1-beta.2"),
            "0.5.1-beta.2.improvement2",
        )

    def test_stable_release_set_builds_current_and_legacy_default_paths(self):
        if not _release_package_fixture_available():
            self.skipTest("npm release-set integration requires generated package datasets")
        with tempfile.TemporaryDirectory() as temp_name:
            output = Path(temp_name) / "npm"
            release_set = build_release_set(ROOT, output, require_fresh=False)
            verified = verify_release_set(output / "release-set.json")

            self.assertEqual(release_set["publishMode"], "manual-npm-auth-then-flow-reconcile")
            self.assertEqual(
                [(item["variant"], item["distTag"]) for item in verified["artifacts"]],
                [("current", "latest"), ("improvement2", "improvement2")],
            )

            current, compatibility = verified["artifacts"]
            self.assertEqual(current["version"], "0.5.1")
            self.assertEqual(compatibility["version"], "0.5.1-improvement2")

            with tarfile.open(compatibility["tarball"], "r:gz") as archive:
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

            with tarfile.open(current["tarball"], "r:gz") as archive:
                names = set(archive.getnames())
                self.assertNotIn("package/compat/poi-plugin-item-improvement2/manifest.json", names)
                manifest_stream = archive.extractfile("package/manifest.json")
                self.assertIsNotNone(manifest_stream)
                manifest = json.loads(manifest_stream.read().decode("utf-8"))
                self.assertEqual(manifest["datasets"]["improvement"]["schemaVersion"], 4)


if __name__ == "__main__":
    unittest.main()
