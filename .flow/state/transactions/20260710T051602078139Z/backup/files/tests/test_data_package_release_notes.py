from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from service.data_package import cli, package_history


class DataPackageReleaseNotesTest(unittest.TestCase):
    def test_set_version_updates_package_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"name":"example","version":"1.0.0"}\n', encoding="utf-8")
            (root / "manifest.json").write_text('{"packageVersion":"1.0.0"}\n', encoding="utf-8")
            with patch.object(cli, "PACKAGE_DIR", root):
                self.assertEqual(cli._write_version("1.0.1"), "1.0.1")
            self.assertEqual(json.loads((root / "package.json").read_text())["version"], "1.0.1")
            self.assertEqual(json.loads((root / "manifest.json").read_text())["packageVersion"], "1.0.1")

    def test_finalize_release_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            changelog = root / "CHANGELOG.md"
            releases = root / "RELEASES.json"
            snapshot = root / "snapshot.json"
            changelog.write_text("# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n", encoding="utf-8")
            releases.write_text("[]\n", encoding="utf-8")
            snapshot.write_text(
                json.dumps({"contentDigest": "abc", "metrics": {"improvement.detailRecordCount": 10}}),
                encoding="utf-8",
            )
            with patch.object(package_history, "CHANGELOG_PATH", changelog), patch.object(
                package_history, "RELEASES_PATH", releases
            ):
                package_history.finalize_release("1.0.1", snapshot)
                package_history.finalize_release("1.0.1", snapshot)
            self.assertEqual(changelog.read_text().count("## [1.0.1]"), 1)
            payload = json.loads(releases.read_text())
            self.assertEqual([entry["version"] for entry in payload], ["1.0.1"])
            self.assertEqual(payload[0]["contentDigest"], "abc")

    def test_rejects_invalid_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"version":"1.0.0"}\n', encoding="utf-8")
            with patch.object(cli, "PACKAGE_DIR", root):
                with self.assertRaisesRegex(ValueError, "invalid semantic version"):
                    cli._write_version("1.0")


if __name__ == "__main__":
    unittest.main()
