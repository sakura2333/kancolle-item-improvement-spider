from __future__ import annotations

"""Prepare and publish a temporary npm beta without mutating the dev source tree.

The canonical package source under ``packages/kancolle-data`` is a tracked
source/template tree.  A complete generated package lives under
``dist/packages/kancolle-data``.  This command copies that generated package to
an isolated, ignored staging directory, injects a prerelease version only into
that staging copy, verifies the final tarball, and optionally publishes it via
the existing idempotent npm reconciliation layer.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from automation.release.npm_registry import (
    NpmPublishError,
    query_dist_tags,
    reconcile_npm_publish,
    resolve_registry,
)

PACKAGE_NAME = "@sakura2333/kancolle-data"
BETA_TAG = "beta"
DEFAULT_SOURCE_PACKAGE = PROJECT_ROOT / "dist" / "packages" / "kancolle-data"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "dist" / "npm-beta"
_PRERELEASE_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-"
    r"[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*$"
)


class TemporaryBetaError(RuntimeError):
    pass




def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _git_status() -> str | None:
    if not (PROJECT_ROOT / ".git").exists():
        return None
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "git status failed").strip()
        raise TemporaryBetaError(detail)
    return completed.stdout


def _validate_workspace_boundaries(source_package: Path, output_root: Path) -> None:
    if source_package == output_root or _is_relative_to(output_root, source_package):
        raise TemporaryBetaError("beta output must not be placed inside the generated source package")
    if _is_relative_to(source_package, output_root):
        raise TemporaryBetaError("generated source package must not be placed inside beta output")
    if _is_relative_to(output_root, PROJECT_ROOT):
        relative = output_root.relative_to(PROJECT_ROOT)
        if not relative.parts or relative.parts[0] != "dist":
            raise TemporaryBetaError(
                "project-local beta output must stay under ignored dist/"
            )


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [str(item) for item in command],
        cwd=cwd,
        text=True,
        capture_output=capture_output,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "command failed").strip()
        raise TemporaryBetaError(f"command failed ({' '.join(command)}): {detail}")
    return completed


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TemporaryBetaError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TemporaryBetaError(f"JSON root must be an object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_prerelease(version: str) -> str:
    value = version.strip()
    if not _PRERELEASE_RE.fullmatch(value):
        raise TemporaryBetaError(
            "temporary beta version must be a SemVer prerelease, "
            "for example 0.5.2-beta or 0.5.2-beta.1"
        )
    return value


def _validate_source_package(source: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if not source.is_dir() or source.is_symlink():
        raise TemporaryBetaError(f"generated npm package directory is missing: {source}")
    package_path = source / "package.json"
    manifest_path = source / "manifest.json"
    package = _load_json(package_path)
    manifest = _load_json(manifest_path)
    if package.get("name") != PACKAGE_NAME:
        raise TemporaryBetaError(f"unexpected npm package name: {package.get('name')!r}")
    if manifest.get("packageVersion") != package.get("version"):
        raise TemporaryBetaError("generated package and manifest versions do not match")
    for relative in (
        "index.js",
        "index.d.ts",
        "improvement/list.json",
        "improvement/detail.nedb",
        "equipment/drop-from.nedb",
        "equipment/sources.nedb",
        "equipment/special-bonuses.nedb",
    ):
        if not (source / relative).is_file():
            raise TemporaryBetaError(f"generated npm package is incomplete: missing {relative}")
    return package, manifest


def _copy_staging(source: Path, staging: Path) -> None:
    if staging.exists() or staging.is_symlink():
        if staging.is_dir() and not staging.is_symlink():
            shutil.rmtree(staging)
        else:
            staging.unlink()
    shutil.copytree(
        source,
        staging,
        symlinks=False,
        ignore=shutil.ignore_patterns("node_modules", "*.tgz", ".DS_Store"),
    )
    shutil.rmtree(staging / "compat", ignore_errors=True)
    (staging / "schemas" / "improvement-detail-v3.schema.json").unlink(missing_ok=True)


def _refresh_staging_manifest(staging: Path, version: str) -> None:
    package_path = staging / "package.json"
    manifest_path = staging / "manifest.json"
    package = _load_json(package_path)
    manifest = _load_json(manifest_path)
    package["version"] = version
    manifest["packageVersion"] = version
    _write_json(package_path, package)

    files: dict[str, dict[str, Any]] = {}
    for path in sorted(staging.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(staging).as_posix()
        if relative in {"manifest.json", "package.json"}:
            continue
        if relative.startswith("compat/") or relative == "schemas/improvement-detail-v3.schema.json":
            continue
        if path.suffix == ".tgz" or "node_modules" in path.parts:
            continue
        files[relative] = {"sha256": _sha256(path), "bytes": path.stat().st_size}
    manifest["files"] = files
    _write_json(manifest_path, manifest)


def _pack(staging: Path, artifacts: Path) -> tuple[Path, dict[str, Any]]:
    artifacts.mkdir(parents=True, exist_ok=True)
    completed = _run(
        [
            "npm",
            "pack",
            "--json",
            "--ignore-scripts",
            "--pack-destination",
            str(artifacts),
        ],
        cwd=staging,
        capture_output=True,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise TemporaryBetaError(f"npm pack returned invalid JSON: {exc}") from exc
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise TemporaryBetaError("npm pack returned an unexpected result")
    filename = str(payload[0].get("filename", "")).strip()
    tarball = artifacts / filename
    if not filename or not tarball.is_file():
        raise TemporaryBetaError(f"npm pack did not create the expected tarball: {tarball}")
    return tarball, payload[0]


def _read_tar_json(archive: tarfile.TarFile, member_name: str) -> dict[str, Any]:
    try:
        member = archive.getmember(member_name)
    except KeyError as exc:
        raise TemporaryBetaError(f"npm tarball is missing {member_name}") from exc
    if not member.isfile() or member.size > 2 * 1024 * 1024:
        raise TemporaryBetaError(f"npm tarball member is not a small regular file: {member_name}")
    stream = archive.extractfile(member)
    if stream is None:
        raise TemporaryBetaError(f"npm tarball member cannot be read: {member_name}")
    try:
        payload = json.loads(stream.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TemporaryBetaError(f"npm tarball member is invalid JSON: {member_name}") from exc
    if not isinstance(payload, dict):
        raise TemporaryBetaError(f"npm tarball JSON root is not an object: {member_name}")
    return payload


def _verify_tarball(tarball: Path, version: str) -> None:
    try:
        with tarfile.open(tarball, "r:gz") as archive:
            names = set(archive.getnames())
            for member in archive.getmembers():
                path = Path(member.name)
                if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                    raise TemporaryBetaError(f"unsafe npm tarball member: {member.name}")
            package = _read_tar_json(archive, "package/package.json")
            manifest = _read_tar_json(archive, "package/manifest.json")
    except tarfile.TarError as exc:
        raise TemporaryBetaError(f"invalid npm tarball: {exc}") from exc

    if package.get("name") != PACKAGE_NAME or package.get("version") != version:
        raise TemporaryBetaError("npm tarball package identity mismatch")
    if manifest.get("packageVersion") != version:
        raise TemporaryBetaError("npm tarball manifest version mismatch")
    if any(name.startswith("package/compat/") for name in names):
        raise TemporaryBetaError("npm beta tarball leaked compatibility staging")
    if "package/schemas/improvement-detail-v3.schema.json" in names:
        raise TemporaryBetaError("npm beta tarball leaked the internal schema-3 filename")


def prepare_beta(
    *,
    version: str,
    source_package: Path = DEFAULT_SOURCE_PACKAGE,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    require_fresh: bool = True,
) -> dict[str, Any]:
    version = _validate_prerelease(version)
    source_package = source_package.resolve()
    output_root = output_root.resolve()
    _validate_workspace_boundaries(source_package, output_root)
    source_package_json, source_manifest = _validate_source_package(source_package)
    workspace_before = _git_status()

    beta_root = output_root / version
    if beta_root.exists() or beta_root.is_symlink():
        if beta_root.is_dir() and not beta_root.is_symlink():
            shutil.rmtree(beta_root)
        else:
            beta_root.unlink()
    staging = beta_root / "package"
    artifacts = beta_root / "artifacts"
    _copy_staging(source_package, staging)
    _refresh_staging_manifest(staging, version)

    _run(["npm", "run", "check"], cwd=staging)
    if require_fresh:
        _run(["npm", "run", "check:fresh"], cwd=staging)
    tarball, pack_result = _pack(staging, artifacts)
    _verify_tarball(tarball, version)

    package_result = {
        "schema": 1,
        "package": PACKAGE_NAME,
        "version": version,
        "tarball": tarball.name,
        "filename": tarball.name,
        "sha256": _sha256(tarball),
        "bytes": tarball.stat().st_size,
        "requireFresh": require_fresh,
    }
    package_result_path = artifacts / "package-result.json"
    _write_json(package_result_path, package_result)

    artifact = {
        "schemaVersion": 1,
        "kind": "temporary-npm-beta-artifact",
        "preparedAt": _utc_now(),
        "package": PACKAGE_NAME,
        "version": version,
        "distTag": BETA_TAG,
        "source": {
            "path": str(source_package),
            "version": source_package_json.get("version"),
            "manifestSha256": _sha256(source_package / "manifest.json"),
            "generatedAt": source_manifest.get("generatedAt"),
        },
        "staging": str(staging),
        "tarball": str(tarball),
        "tarballSha256": package_result["sha256"],
        "packageResult": str(package_result_path),
        "pack": {
            "filename": pack_result.get("filename"),
            "files": len(pack_result.get("files", [])) if isinstance(pack_result.get("files"), list) else None,
            "unpackedSize": pack_result.get("unpackedSize"),
        },
    }
    workspace_after = _git_status()
    if workspace_before != workspace_after:
        shutil.rmtree(beta_root, ignore_errors=True)
        raise TemporaryBetaError(
            "temporary beta preparation changed the project Git workspace; output was discarded"
        )
    artifact["workspaceStatusPreserved"] = True
    artifact_path = beta_root / "beta-artifact.json"
    _write_json(artifact_path, artifact)
    return {**artifact, "artifactManifest": str(artifact_path)}


def publish_beta(
    *,
    version: str,
    source_package: Path = DEFAULT_SOURCE_PACKAGE,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    require_fresh: bool = True,
    registry: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    if not confirm:
        raise TemporaryBetaError("publishing requires --confirm")
    artifact = prepare_beta(
        version=version,
        source_package=source_package,
        output_root=output_root,
        require_fresh=require_fresh,
    )
    artifact_manifest = Path(str(artifact["artifactManifest"]))
    package_result = Path(str(artifact["packageResult"]))
    audit_output = artifact_manifest.parent / "publish-audit.json"
    try:
        audit = reconcile_npm_publish(
            package_result_path=package_result,
            audit_output=audit_output,
            tag=BETA_TAG,
            registry=registry,
            publish=True,
        )
    except NpmPublishError as exc:
        raise TemporaryBetaError(str(exc)) from exc
    return {"artifact": artifact, "publishAudit": audit, "publishAuditPath": str(audit_output)}


def remove_beta_tag(*, registry: str | None = None, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        raise TemporaryBetaError("removing the beta dist-tag requires --confirm")
    resolved = resolve_registry(registry)
    before = query_dist_tags(PACKAGE_NAME, registry=resolved)
    completed = subprocess.run(
        ["npm", "dist-tag", "rm", PACKAGE_NAME, BETA_TAG, "--registry", resolved],
        text=True,
        capture_output=True,
        check=False,
    )
    after = query_dist_tags(PACKAGE_NAME, registry=resolved)
    if completed.returncode != 0 and BETA_TAG in after:
        detail = (completed.stderr or completed.stdout or "npm dist-tag rm failed").strip()
        raise TemporaryBetaError(detail)
    return {
        "schemaVersion": 1,
        "package": PACKAGE_NAME,
        "tag": BETA_TAG,
        "registry": resolved,
        "before": before.get(BETA_TAG),
        "after": after.get(BETA_TAG),
        "removed": BETA_TAG not in after,
    }


def _path(value: str) -> Path:
    return Path(value).expanduser()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare or publish an isolated temporary npm beta artifact"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("prepare", "publish"):
        command = sub.add_parser(name)
        command.add_argument("--version", required=True)
        command.add_argument("--source-package", type=_path, default=DEFAULT_SOURCE_PACKAGE)
        command.add_argument("--output-root", type=_path, default=DEFAULT_OUTPUT_ROOT)
        command.add_argument("--no-fresh", action="store_true")
        if name == "publish":
            command.add_argument("--registry")
            command.add_argument("--confirm", action="store_true")

    remove = sub.add_parser("remove-tag")
    remove.add_argument("--registry")
    remove.add_argument("--confirm", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare_beta(
                version=args.version,
                source_package=args.source_package,
                output_root=args.output_root,
                require_fresh=not args.no_fresh,
            )
        elif args.command == "publish":
            result = publish_beta(
                version=args.version,
                source_package=args.source_package,
                output_root=args.output_root,
                require_fresh=not args.no_fresh,
                registry=args.registry,
                confirm=args.confirm,
            )
        else:
            result = remove_beta_tag(registry=args.registry, confirm=args.confirm)
    except TemporaryBetaError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
