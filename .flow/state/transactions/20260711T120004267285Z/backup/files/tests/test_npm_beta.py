from __future__ import annotations

import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from script.project.npm_beta import (
    TemporaryBetaError,
    prepare_beta,
    publish_beta,
)


class TemporaryNpmBetaTest(unittest.TestCase):
    def _write_package(self, root: Path) -> Path:
        package = root / "generated-package"
        for directory in (
            "improvement",
            "equipment",
            "schemas",
            "scripts",
            "compat/internal",
        ):
            (package / directory).mkdir(parents=True, exist_ok=True)
        package_json = {
            "name": "@sakura2333/kancolle-data",
            "version": "0.5.1",
            "main": "index.js",
            "files": [
                "index.js",
                "index.d.ts",
                "manifest.json",
                "improvement/",
                "equipment/",
                "schemas/",
                "scripts/",
            ],
            "scripts": {
                "check": "node -e \"const p=require('./package.json');const m=require('./manifest.json');if(p.version!==m.packageVersion)process.exit(2)\"",
                "check:fresh": "node -e \"const m=require('./manifest.json');if(m.datasets.improvement.status!=='ok')process.exit(3)\"",
            },
        }
        manifest = {
            "packageVersion": "0.5.1",
            "generatedAt": "2026-07-11T00:00:00Z",
            "datasets": {"improvement": {"status": "ok"}},
            "files": {},
        }
        (package / "package.json").write_text(json.dumps(package_json), encoding="utf-8")
        (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (package / "index.js").write_text("module.exports = {}\n", encoding="utf-8")
        (package / "index.d.ts").write_text("declare const data: object; export = data;\n", encoding="utf-8")
        (package / "improvement/list.json").write_text("[]\n", encoding="utf-8")
        (package / "improvement/detail.nedb").write_text("", encoding="utf-8")
        (package / "equipment/drop-from.nedb").write_text("", encoding="utf-8")
        (package / "equipment/sources.nedb").write_text("", encoding="utf-8")
        (package / "equipment/special-bonuses.nedb").write_text("", encoding="utf-8")
        (package / "schemas/improvement-detail.schema.json").write_text("{}\n", encoding="utf-8")
        (package / "schemas/improvement-detail-v3.schema.json").write_text("{}\n", encoding="utf-8")
        (package / "scripts/check-fresh.js").write_text("", encoding="utf-8")
        (package / "compat/internal/private.json").write_text("{}\n", encoding="utf-8")
        return package

    def test_prepare_uses_isolated_dist_staging_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source = self._write_package(root)
            original_package = (source / "package.json").read_bytes()
            original_manifest = (source / "manifest.json").read_bytes()

            result = prepare_beta(
                version="0.5.2-beta.0",
                source_package=source,
                output_root=root / "dist" / "npm" / "kancolle-data",
            )

            self.assertEqual((source / "package.json").read_bytes(), original_package)
            self.assertEqual((source / "manifest.json").read_bytes(), original_manifest)
            staging = Path(result["staging"])
            tarball = Path(result["tarball"])
            self.assertEqual(
                staging,
                root / "dist" / "npm" / "kancolle-data" / "0.5.2-beta.0" / "package",
            )
            self.assertTrue(staging.is_dir())
            self.assertTrue(tarball.is_file())
            self.assertFalse((staging / "compat").exists())
            self.assertFalse((staging / "schemas/improvement-detail-v3.schema.json").exists())
            self.assertEqual(json.loads((staging / "package.json").read_text())["version"], "0.5.2-beta.0")
            self.assertEqual(json.loads((staging / "manifest.json").read_text())["packageVersion"], "0.5.2-beta.0")

            with tarfile.open(tarball, "r:gz") as archive:
                names = set(archive.getnames())
                package_json = json.loads(
                    archive.extractfile("package/package.json").read().decode("utf-8")
                )
            self.assertEqual(package_json["version"], "0.5.2-beta.0")
            self.assertFalse(any(name.startswith("package/compat/") for name in names))
            self.assertNotIn("package/schemas/improvement-detail-v3.schema.json", names)

    def test_prepare_rejects_non_prerelease_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source = self._write_package(root)
            with self.assertRaises(TemporaryBetaError):
                prepare_beta(
                    version="0.5.2",
                    source_package=source,
                    output_root=root / "output",
                )

    def test_publish_requires_explicit_confirmation_before_preparing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source = self._write_package(root)
            output = root / "output"
            with self.assertRaises(TemporaryBetaError):
                publish_beta(
                    version="0.5.2-beta",
                    source_package=source,
                    output_root=output,
                    confirm=False,
                )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
