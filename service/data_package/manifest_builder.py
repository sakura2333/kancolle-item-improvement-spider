from __future__ import annotations

import hashlib
import json
from pathlib import Path

from service.data_package.package_paths import PACKAGE_DIR
from util.json_utils import write_json

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def package_version() -> str:
    with (PACKAGE_DIR / "package.json").open("r", encoding="utf-8") as file:
        return str(json.load(file)["version"])

def refresh_package_manifest() -> dict:
    """Refresh package version and file hashes without refetching source data."""

    manifest_path = PACKAGE_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["packageVersion"] = package_version()
    files = {}
    for path in sorted(PACKAGE_DIR.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(PACKAGE_DIR).as_posix()
        if relative in {"manifest.json", "package.json"}:
            continue
        if relative.startswith("compat/") or relative == "schemas/improvement-detail-v3.schema.json":
            continue
        if path.suffix == ".tgz" or "node_modules" in path.parts:
            continue
        files[relative] = {"sha256": _sha256(path), "bytes": path.stat().st_size}
    manifest["files"] = files
    write_json(str(manifest_path), manifest, mode="w", log=True)
    return manifest


# Backward compatibility for internal imports created before 1.0.2.
_package_version = package_version
