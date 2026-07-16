from __future__ import annotations

"""Public data-release npm variants for the frozen build candidate.

The canonical package is published to ``latest`` with WebP image assets. The
``improvement2`` dist-tag is a deliberately minimal legacy package containing
only the frozen schema-3 improvement projection and official useitem PNGs.
"""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from typing import Any

from automation.release.consumer_identity import (
    CURRENT_VARIANT,
    IDENTITY_SCHEMA_VERSION as CONSUMER_IDENTITY_SCHEMA_VERSION,
    IMPROVEMENT2_VARIANT,
    inspect_tarball as inspect_consumer_tarball,
)
from automation.release.npm_business_identity import (
    IDENTITY_SCHEMA_VERSION as NPM_BUSINESS_IDENTITY_SCHEMA_VERSION,
    inspect_tarball as inspect_npm_business_tarball,
)

from automation.common.process import (
    AutomationError,
    parse_json_output,
    project_env,
    run,
    sha256_file,
    write_json,
)

ProjectCommandError = AutomationError

PACKAGE_NAME = "@sakura2333/kancolle-data"
CURRENT_TAG = "latest"
IMPROVEMENT2_TAG = "improvement2"
IMPROVEMENT2_CONSUMER = "poi-plugin-item-improvement2"

_SCHEMA4_ONLY_IMPROVEMENT_METADATA = {
    "effectExpectationAvailableCount",
    "effectExpectationUnavailableCount",
    "stepCount",
    "upgradeAvailableCount",
}

def improvement2_version(current_version: str) -> str:
    value = current_version.strip()
    if not value:
        raise ProjectCommandError("npm package version is empty")
    if "+" in value:
        value = value.split("+", 1)[0]
    return f"{value}.improvement2" if "-" in value else f"{value}-improvement2"

def _package_result(package_dir: Path, output_dir: Path, *, require_fresh: bool) -> dict[str, Any]:
    run(["npm", "run", "check"], cwd=package_dir, env=project_env(package_dir))
    if require_fresh:
        run(["npm", "run", "check:fresh"], cwd=package_dir, env=project_env(package_dir))
    completed = run(
        [
            "npm",
            "pack",
            "--json",
            "--ignore-scripts",
            "--pack-destination",
            str(output_dir),
        ],
        cwd=package_dir,
        env=project_env(package_dir),
        capture_output=True,
    )
    payload = parse_json_output(completed.stdout)
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ProjectCommandError("npm pack returned an unexpected result")
    filename = str(payload[0].get("filename", "")).strip()
    tarball = output_dir / filename
    if not filename or not tarball.is_file():
        raise ProjectCommandError(f"npm pack did not create the expected tarball: {tarball}")
    package_json = json.loads((package_dir / "package.json").read_text(encoding="utf-8"))
    return {
        "schema": 1,
        "package": str(package_json["name"]),
        "version": str(package_json["version"]),
        "tarball": tarball.name,
        "filename": tarball.name,
        "sha256": sha256_file(tarball),
        "bytes": tarball.stat().st_size,
        "requireFresh": require_fresh,
    }

def _refresh_staging_manifest(package_dir: Path, manifest: dict[str, Any]) -> None:
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(package_dir).as_posix()
        if relative in {"manifest.json", "package.json"}:
            continue
        if path.suffix == ".tgz" or "node_modules" in path.parts:
            continue
        files[relative] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    manifest["files"] = files
    write_json(package_dir / "manifest.json", manifest)

def _compatibility_manifest(source_package: Path, compat_version: str) -> dict[str, Any]:
    canonical = json.loads((source_package / "manifest.json").read_text(encoding="utf-8"))
    compat = json.loads(
        (
            source_package
            / "compat"
            / IMPROVEMENT2_CONSUMER
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    compat_datasets = compat.get("datasets", {})
    compat_dataset = compat_datasets.get("improvement", {})
    compat_useitems = compat_datasets.get("useitemIcons", {})
    if compat.get("consumer") != IMPROVEMENT2_CONSUMER:
        raise ProjectCommandError("improvement2 compatibility manifest consumer mismatch")
    if compat_dataset.get("schemaVersion") != 3 or compat_dataset.get("listSchemaVersion") != 2:
        raise ProjectCommandError("improvement2 compatibility manifest is not schema 3/list schema 2")
    if compat_useitems.get("format") != "png":
        raise ProjectCommandError("improvement2 compatibility manifest does not expose PNG useitems")

    canonical_improvement = deepcopy(canonical.get("datasets", {}).get("improvement", {}))
    for key in _SCHEMA4_ONLY_IMPROVEMENT_METADATA:
        canonical_improvement.pop(key, None)
    canonical_improvement.update(
        {
            "schemaVersion": 3,
            "listSchemaVersion": 2,
            "list": "improvement/list.json",
            "detail": "improvement/detail.nedb",
            "detailRecordCount": compat_dataset.get("detailRecordCount"),
            "routeCount": compat_dataset.get("routeCount"),
        }
    )
    return {
        "packageVersion": compat_version,
        "generatedAt": compat.get("generatedAt") or canonical.get("generatedAt"),
        "consumer": IMPROVEMENT2_CONSUMER,
        "datasets": {
            "improvement": canonical_improvement,
            "useitemIcons": deepcopy(compat_useitems),
        },
        "sources": {
            key: value
            for key, value in (canonical.get("sources") or {}).items()
            if key in {"akashiList", "officialKanColleAssets"}
        },
    }


def _copy_required(source: Path, target: Path) -> None:
    if not source.exists():
        raise ProjectCommandError(f"improvement2 source file is missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def _build_improvement2_staging(source_package: Path, staging: Path) -> str:
    staging.mkdir(parents=True, exist_ok=False)
    package_json = json.loads((source_package / "package.json").read_text(encoding="utf-8"))
    if package_json.get("name") != PACKAGE_NAME:
        raise ProjectCommandError("unexpected npm package name for improvement2 projection")
    compat_version = improvement2_version(str(package_json["version"]))
    package_json["version"] = compat_version
    package_json["description"] = (
        "Frozen schema-3 improvement data and official useitem PNGs for "
        "poi-plugin-item-improvement2"
    )
    package_json["files"] = [
        "index.js",
        "index.d.ts",
        "manifest.json",
        "README.md",
        "CHANGELOG.md",
        "LICENSES.md",
        "RELEASES.json",
        "scripts/check-fresh.js",
        "schemas/improvement-detail.schema.json",
        "improvement/",
        "assets/useitem/",
    ]
    package_json["scripts"]["check"] = (
        "node -e \"const d=require('./');const fs=require('fs');"
        "const m=JSON.parse(fs.readFileSync(d.manifestPath));"
        "for(const p of [d.manifestPath,d.releasesPath,d.improvement.listPath,"
        "d.improvement.detailPath,d.schemas.improvementDetailPath])"
        "if(!fs.existsSync(p))throw new Error('missing '+p);"
        "if(m.consumer!=='poi-plugin-item-improvement2')throw new Error('unexpected consumer');"
        "if(m.datasets.improvement.schemaVersion!==3)throw new Error('unexpected improvement schema');"
        "if(m.datasets.improvement.listSchemaVersion!==2)throw new Error('unexpected list schema');"
        "if(m.datasets.useitemIcons.format!=='png')throw new Error('unexpected useitem format');"
        "if((m.datasets.useitemIcons.missingIds||[]).length)throw new Error('missing useitem icons');"
        "for(const id of m.datasets.useitemIcons.requiredIds||[])"
        "if(!fs.existsSync(d.assets.useitemPath(id)))throw new Error('missing icon '+id)\""
    )
    (staging / "package.json").write_text(
        json.dumps(package_json, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    for relative in ("CHANGELOG.md", "LICENSES.md", "RELEASES.json"):
        _copy_required(source_package / relative, staging / relative)

    compat_root = source_package / "compat" / IMPROVEMENT2_CONSUMER
    _copy_required(compat_root / "improvement", staging / "improvement")
    _copy_required(compat_root / "assets" / "useitem", staging / "assets" / "useitem")
    _copy_required(
        source_package / "schemas" / "improvement-detail-v3.schema.json",
        staging / "schemas" / "improvement-detail.schema.json",
    )

    (staging / "index.js").write_text(
        "'use strict'\n\n"
        "const path = require('path')\n"
        "const resolveData = (...parts) => path.join(__dirname, ...parts)\n\n"
        "module.exports = Object.freeze({\n"
        "  rootPath: __dirname,\n"
        "  manifestPath: resolveData('manifest.json'),\n"
        "  releasesPath: resolveData('RELEASES.json'),\n"
        "  improvement: Object.freeze({\n"
        "    listPath: resolveData('improvement', 'list.json'),\n"
        "    detailPath: resolveData('improvement', 'detail.nedb'),\n"
        "  }),\n"
        "  schemas: Object.freeze({\n"
        "    improvementDetailPath: resolveData('schemas', 'improvement-detail.schema.json'),\n"
        "  }),\n"
        "  assets: Object.freeze({\n"
        "    useitemPath(id) { return resolveData('assets', 'useitem', `${Number(id)}.png`) },\n"
        "  }),\n"
        "})\n",
        encoding="utf-8",
    )
    (staging / "index.d.ts").write_text(
        "export interface Improvement2DataPaths {\n"
        "  rootPath: string\n"
        "  manifestPath: string\n"
        "  releasesPath: string\n"
        "  improvement: { listPath: string; detailPath: string }\n"
        "  schemas: { improvementDetailPath: string }\n"
        "  assets: { useitemPath(id: number | string): string }\n"
        "}\n"
        "declare const paths: Improvement2DataPaths\n"
        "export = paths\n",
        encoding="utf-8",
    )
    (staging / "scripts").mkdir(parents=True, exist_ok=True)
    (staging / "scripts" / "check-fresh.js").write_text(
        "'use strict'\n"
        "const fs = require('fs')\n"
        "const path = require('path')\n"
        "const root = path.resolve(__dirname, '..')\n"
        "const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'))\n"
        "const dataset = manifest.datasets && manifest.datasets.improvement\n"
        "if (!dataset || dataset.status !== 'ok') throw new Error('improvement data is not fresh')\n"
        "if (dataset.collectionCompletedInRun !== true) throw new Error('improvement data was not rebuilt')\n"
        "if (!Array.isArray(dataset.fetches) || dataset.fetches.length === 0) throw new Error('missing improvement fetch audit')\n"
        "for (const fetchInfo of dataset.fetches) {\n"
        "  if (fetchInfo.status !== 'fresh' || fetchInfo.validatedInRun !== true || fetchInfo.usedCacheFallback === true) {\n"
        "    throw new Error(`improvement source was not freshly validated: ${fetchInfo.url}`)\n"
        "  }\n"
        "}\n"
        "console.log('improvement2 source freshness checks passed')\n",
        encoding="utf-8",
    )

    canonical_readme = (source_package / "README.md").read_text(encoding="utf-8")
    (staging / "README.md").write_text(
        "# Improvement2 compatibility distribution\n\n"
        "This legacy npm variant contains only the frozen schema-3 improvement "
        "projection and official `assets/useitem/{id}.png` files required by "
        "`poi-plugin-item-improvement2`. It intentionally excludes equipment "
        "datasets and equipment images.\n\n"
        + canonical_readme,
        encoding="utf-8",
    )

    manifest = _compatibility_manifest(source_package, compat_version)
    _refresh_staging_manifest(staging, manifest)
    return compat_version

def _tar_member_json(archive: tarfile.TarFile, name: str) -> Any:
    stream = archive.extractfile(name)
    if stream is None:
        raise ProjectCommandError(f"npm tarball member cannot be read: {name}")
    return json.loads(stream.read().decode("utf-8"))

def _verify_tarball(
    result: dict[str, Any],
    *,
    schema_version: int,
    compatibility: bool,
    release_version: str,
) -> dict[str, str]:
    tarball = Path(str(result["tarball"]))
    if not tarball.is_absolute():
        tarball = Path(str(result.get("_baseDir", "."))) / tarball
    tarball = tarball.resolve()
    with tarfile.open(tarball, "r:gz") as archive:
        names = set(archive.getnames())
        package_json = _tar_member_json(archive, "package/package.json")
        manifest = _tar_member_json(archive, "package/manifest.json")
        releases = _tar_member_json(archive, "package/RELEASES.json")
        if package_json.get("name") != PACKAGE_NAME or package_json.get("version") != result["version"]:
            raise ProjectCommandError("npm tarball identity mismatch")
        if manifest.get("packageVersion") != result["version"]:
            raise ProjectCommandError("npm tarball manifest version mismatch")
        if manifest.get("datasets", {}).get("improvement", {}).get("schemaVersion") != schema_version:
            raise ProjectCommandError("npm tarball improvement schema mismatch")
        if not isinstance(releases, list):
            raise ProjectCommandError("npm tarball RELEASES.json must contain an array")
        has_internal_compat = any(name.startswith("package/compat/") for name in names)
        if has_internal_compat:
            raise ProjectCommandError("published npm tarball leaked internal compatibility staging")
        if "package/schemas/improvement-detail-v3.schema.json" in names:
            raise ProjectCommandError("published npm tarball leaked the internal v3 schema filename")
        useitem_names = {
            name for name in names if name.startswith("package/assets/useitem/")
        }
        if compatibility:
            if any(name.startswith("package/equipment/") for name in names):
                raise ProjectCommandError("improvement2 tarball must not contain equipment datasets")
            if any(name.startswith("package/assets/equip/") for name in names):
                raise ProjectCommandError("improvement2 tarball must not contain equipment images")
            if any(name.endswith(".webp") for name in useitem_names):
                raise ProjectCommandError("improvement2 tarball must expose useitem PNGs only")
            if any(
                not name.endswith(".png")
                for name in useitem_names
                if not name.endswith("/")
            ):
                raise ProjectCommandError("improvement2 tarball contains an unsupported useitem asset")
            if set(manifest.get("datasets", {})) != {"improvement", "useitemIcons"}:
                raise ProjectCommandError("improvement2 manifest leaked canonical datasets")
            if manifest.get("datasets", {}).get("useitemIcons", {}).get("format") != "png":
                raise ProjectCommandError("improvement2 manifest does not declare PNG useitems")
            stream = archive.extractfile("package/improvement/detail.nedb")
            if stream is None:
                raise ProjectCommandError("compatibility tarball lacks improvement detail")
            for line_number, raw in enumerate(stream.read().decode("utf-8").splitlines(), start=1):
                if not raw.strip():
                    continue
                record = json.loads(raw)
                if set(record) != {"id", "name", "improvementList"}:
                    raise ProjectCommandError(
                        f"improvement2 record {line_number} is not the frozen top-level VO"
                    )
                for route in record["improvementList"]:
                    if "stepList" in route:
                        raise ProjectCommandError(
                            f"improvement2 record {record['id']} leaked schema-4 route fields"
                        )
        else:
            if any(name.endswith(".png") for name in useitem_names):
                raise ProjectCommandError("canonical tarball must expose useitem WebP only")
            if any(
                not name.endswith(".webp")
                for name in useitem_names
                if not name.endswith("/")
            ):
                raise ProjectCommandError("canonical tarball contains an unsupported useitem asset")
            if manifest.get("datasets", {}).get("useitemIcons", {}).get("format") != "webp":
                raise ProjectCommandError("canonical manifest does not declare WebP useitems")

    variant = IMPROVEMENT2_VARIANT if compatibility else CURRENT_VARIANT
    consumer_identity = inspect_consumer_tarball(tarball, variant=variant)
    business_identity = inspect_npm_business_tarball(tarball)
    return {
        "contentDigest": str(consumer_identity["contentDigest"]),
        "businessDigest": str(business_identity["businessDigest"]),
    }

def inspect_business_variants(
    package_dir: Path,
    *,
    output: Path | None = None,
) -> dict[str, Any]:
    """Pack both public variants and return their normalized npm business identities."""

    package_dir = package_dir.resolve()
    with tempfile.TemporaryDirectory(prefix="kancolle-data-business-inspect-") as temp_name:
        temp = Path(temp_name).resolve()
        current = _package_result(package_dir, temp, require_fresh=False)
        current_verify = dict(current)
        current_verify["_baseDir"] = str(temp)
        current_identity = _verify_tarball(
            current_verify,
            schema_version=4,
            compatibility=False,
            release_version=str(current["version"]),
        )

        staging = temp / "improvement2-package"
        compat_version = _build_improvement2_staging(package_dir, staging)
        compatibility = _package_result(staging, temp, require_fresh=False)
        if compatibility["version"] != compat_version:
            raise ProjectCommandError("improvement2 package version changed during inspection")
        compatibility_verify = dict(compatibility)
        compatibility_verify["_baseDir"] = str(temp)
        compatibility_identity = _verify_tarball(
            compatibility_verify,
            schema_version=3,
            compatibility=True,
            release_version=str(current["version"]),
        )

    payload = {
        "schemaVersion": 1,
        "package": PACKAGE_NAME,
        "npmBusinessIdentities": {
            "schemaVersion": NPM_BUSINESS_IDENTITY_SCHEMA_VERSION,
            "current": current_identity["businessDigest"],
            "improvement2": compatibility_identity["businessDigest"],
        },
    }
    if output is not None:
        write_json(output.resolve(), payload)
    return payload


def build_release_set(
    root: Path,
    output_dir: Path,
    *,
    require_fresh: bool = True,
    package_dir: Path | None = None,
) -> dict[str, Any]:
    package_dir = (package_dir or (root / "dist" / "packages" / "kancolle-data")).resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    current = _package_result(package_dir, output_dir, require_fresh=require_fresh)

    with tempfile.TemporaryDirectory(prefix="kancolle-data-improvement2-") as temp_name:
        staging = Path(temp_name) / "package"
        compat_version = _build_improvement2_staging(package_dir, staging)
        compatibility = _package_result(staging, output_dir, require_fresh=require_fresh)
    if compatibility["version"] != compat_version:
        raise ProjectCommandError("improvement2 package version changed during packing")

    current_verify = dict(current)
    current_verify["_baseDir"] = str(output_dir)
    compatibility_verify = dict(compatibility)
    compatibility_verify["_baseDir"] = str(output_dir)
    current_identity = _verify_tarball(
        current_verify,
        schema_version=4,
        compatibility=False,
        release_version=str(current["version"]),
    )
    compatibility_identity = _verify_tarball(
        compatibility_verify,
        schema_version=3,
        compatibility=True,
        release_version=str(current["version"]),
    )
    current.update(current_identity)
    compatibility.update(compatibility_identity)
    write_json(output_dir / "current.package-result.json", current)
    write_json(output_dir / "improvement2.package-result.json", compatibility)

    release_set = {
        "schemaVersion": 1,
        "package": PACKAGE_NAME,
        "policy": "frozen-build-candidate-with-improvement2-projection",
        "publishMode": "idempotent-release-action",
        "consumerIdentities": {
            "schemaVersion": CONSUMER_IDENTITY_SCHEMA_VERSION,
            "current": current_identity["contentDigest"],
            "improvement2": compatibility_identity["contentDigest"],
        },
        "npmBusinessIdentities": {
            "schemaVersion": NPM_BUSINESS_IDENTITY_SCHEMA_VERSION,
            "current": current_identity["businessDigest"],
            "improvement2": compatibility_identity["businessDigest"],
        },
        "artifacts": [
            {
                "variant": "current",
                "consumer": None,
                "distTag": CURRENT_TAG,
                "packageResult": "current.package-result.json",
                **current,
            },
            {
                "variant": "improvement2",
                "consumer": IMPROVEMENT2_CONSUMER,
                "distTag": IMPROVEMENT2_TAG,
                "packageResult": "improvement2.package-result.json",
                **compatibility,
            },
        ],
    }
    write_json(output_dir / "release-set.json", release_set)
    return release_set

def verify_release_set(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1 or payload.get("package") != PACKAGE_NAME:
        raise ProjectCommandError("unsupported npm release-set manifest")
    if payload.get("policy") != "frozen-build-candidate-with-improvement2-projection":
        raise ProjectCommandError("npm release-set policy mismatch")
    if payload.get("publishMode") != "idempotent-release-action":
        raise ProjectCommandError("npm release-set publish mode mismatch")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 2:
        raise ProjectCommandError("npm release-set must contain current and improvement2 artifacts")
    expected = {"current": (CURRENT_TAG, 4), "improvement2": (IMPROVEMENT2_TAG, 3)}
    current_artifact = next(
        (item for item in artifacts if isinstance(item, dict) and item.get("variant") == "current"),
        None,
    )
    if current_artifact is None:
        raise ProjectCommandError("npm release-set lacks the current variant")
    canonical_version = str(current_artifact.get("version") or "").strip()
    if not canonical_version:
        raise ProjectCommandError("npm release-set current version is empty")
    identities = payload.get("consumerIdentities")
    if (
        not isinstance(identities, dict)
        or identities.get("schemaVersion") != CONSUMER_IDENTITY_SCHEMA_VERSION
    ):
        raise ProjectCommandError("npm release-set consumer identity contract mismatch")
    business_identities = payload.get("npmBusinessIdentities")
    if (
        not isinstance(business_identities, dict)
        or business_identities.get("schemaVersion") != NPM_BUSINESS_IDENTITY_SCHEMA_VERSION
    ):
        raise ProjectCommandError("npm release-set business identity contract mismatch")
    seen: set[str] = set()
    for artifact in artifacts:
        variant = artifact.get("variant")
        if variant not in expected or variant in seen:
            raise ProjectCommandError("npm release-set contains an unknown or duplicate variant")
        seen.add(variant)
        tag, schema = expected[variant]
        if artifact.get("distTag") != tag:
            raise ProjectCommandError(f"npm release-set variant {variant} has an invalid dist-tag")
        if artifact.get("package") != PACKAGE_NAME:
            raise ProjectCommandError(f"npm release-set variant {variant} package mismatch")
        expected_consumer = None if variant == "current" else IMPROVEMENT2_CONSUMER
        if artifact.get("consumer") != expected_consumer:
            raise ProjectCommandError(f"npm release-set variant {variant} consumer mismatch")
        tarball = Path(str(artifact.get("tarball", "")))
        if not tarball.is_absolute():
            tarball = path.parent / tarball
        tarball = tarball.resolve()
        if not tarball.is_file() or sha256_file(tarball) != artifact.get("sha256"):
            raise ProjectCommandError(f"npm release-set variant {variant} tarball identity mismatch")
        if (
            variant == "improvement2"
            and artifact.get("version") != improvement2_version(canonical_version)
        ):
            raise ProjectCommandError("npm release-set improvement2 version mismatch")
        verification_artifact = dict(artifact)
        verification_artifact["_baseDir"] = str(path.parent)
        verification = _verify_tarball(
            verification_artifact,
            schema_version=schema,
            compatibility=variant == "improvement2",
            release_version=canonical_version,
        )
        content_digest = verification["contentDigest"]
        business_digest = verification["businessDigest"]
        if artifact.get("contentDigest") != content_digest:
            raise ProjectCommandError(
                f"npm release-set variant {variant} contentDigest metadata mismatch"
            )
        if artifact.get("businessDigest") != business_digest:
            raise ProjectCommandError(
                f"npm release-set variant {variant} businessDigest metadata mismatch"
            )
        if str(identities.get(variant) or "") != content_digest:
            raise ProjectCommandError(
                f"npm release-set consumer identity mismatch for {variant}"
            )
        if str(business_identities.get(variant) or "") != business_digest:
            raise ProjectCommandError(
                f"npm release-set business identity mismatch for {variant}"
            )
    return payload

def hydrate_published_artifacts(
    manifest_path: Path,
    published_versions_path: Path,
) -> dict[str, Any]:
    """Replace already-published variants with their immutable Registry tarballs.

    Stateless reconciliation may reuse an npm version that already carries the
    current npm business content.  The frozen candidate must then contain the
    exact Registry bytes for every variant that already exists, while retaining
    locally built tarballs only for missing variants that still need publication.
    """

    manifest_path = manifest_path.resolve()
    release_dir = manifest_path.parent
    if not manifest_path.is_file():
        raise ProjectCommandError(f"npm release-set manifest is missing: {manifest_path}")
    if not published_versions_path.is_file():
        raise ProjectCommandError(
            f"published npm version inventory is missing: {published_versions_path}"
        )

    published_payload = json.loads(published_versions_path.read_text(encoding="utf-8"))
    if not isinstance(published_payload, list) or not all(
        isinstance(item, str) and item.strip() for item in published_payload
    ):
        raise ProjectCommandError("published npm version inventory must be a string array")
    published_versions = {item.strip() for item in published_payload}

    release_set = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = release_set.get("artifacts")
    if not isinstance(artifacts, list):
        raise ProjectCommandError("npm release-set artifacts must contain an array")

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ProjectCommandError("npm release-set artifact must be an object")
        version = str(artifact.get("version") or "").strip()
        package = str(artifact.get("package") or "").strip()
        if not version or not package:
            raise ProjectCommandError("npm release-set artifact identity is incomplete")
        if version not in published_versions:
            continue

        with tempfile.TemporaryDirectory(prefix="npm-registry-artifact-") as temp_name:
            temp = Path(temp_name).resolve()
            completed = subprocess.run(
                [
                    "npm",
                    "pack",
                    f"{package}@{version}",
                    "--ignore-scripts",
                    "--json",
                    "--pack-destination",
                    str(temp),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            combined = "\n".join(
                part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
            )
            if completed.returncode:
                raise ProjectCommandError(combined or f"npm pack failed for {version}")
            try:
                packed = json.loads(completed.stdout)
                filename = str(packed[0]["filename"])
            except (json.JSONDecodeError, IndexError, KeyError, TypeError) as exc:
                raise ProjectCommandError(
                    f"npm pack returned invalid JSON for {version}: {exc}"
                ) from exc

            source = Path(filename)
            if not source.is_absolute():
                source = temp / source
            source = source.resolve()
            if source.parent != temp or not source.is_file() or source.is_symlink():
                raise ProjectCommandError(
                    f"npm pack produced an unsafe tarball for {version}"
                )
            with tarfile.open(source, "r:gz") as archive:
                package_json = _tar_member_json(archive, "package/package.json")
            if package_json.get("name") != package or package_json.get("version") != version:
                raise ProjectCommandError(f"registry tarball identity mismatch for {version}")

            target = release_dir / source.name
            shutil.copy2(source, target)

        variant = str(artifact.get("variant") or "")
        if variant not in {CURRENT_VARIANT, IMPROVEMENT2_VARIANT}:
            raise ProjectCommandError(f"unknown npm release-set variant: {variant}")
        registry_content_digest = str(
            inspect_consumer_tarball(target, variant=variant)["contentDigest"]
        )
        registry_business_digest = str(
            inspect_npm_business_tarball(target)["businessDigest"]
        )
        expected_content_digest = str(artifact.get("contentDigest") or "")
        expected_business_digest = str(artifact.get("businessDigest") or "")
        if (
            registry_content_digest != expected_content_digest
            or registry_business_digest != expected_business_digest
        ):
            raise ProjectCommandError(
                f"immutable npm registry conflict: {version} actual package business content "
                f"does not match the frozen {variant} identity"
            )

        artifact.update(
            {
                "tarball": target.name,
                "filename": target.name,
                "sha256": sha256_file(target),
                "bytes": target.stat().st_size,
                "contentDigest": registry_content_digest,
                "businessDigest": registry_business_digest,
            }
        )
        result_relative = str(artifact.get("packageResult") or "").strip()
        result_path = (release_dir / result_relative).resolve()
        if not result_relative or result_path.parent != release_dir or not result_path.is_file():
            raise ProjectCommandError(
                f"npm release-set package result is missing or unsafe for {version}"
            )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("package") != package or result.get("version") != version:
            raise ProjectCommandError(f"npm package result identity mismatch for {version}")
        result.update(
            {
                "tarball": target.name,
                "filename": target.name,
                "sha256": artifact["sha256"],
                "bytes": artifact["bytes"],
                "contentDigest": registry_content_digest,
                "businessDigest": registry_business_digest,
            }
        )
        write_json(result_path, result)

    write_json(manifest_path, release_set)
    return verify_release_set(manifest_path)

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Build or verify frozen npm release variants")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--project", type=Path, default=Path.cwd())
    build.add_argument("--package-dir", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--no-fresh", action="store_true")
    inspect_business = sub.add_parser("inspect-business")
    inspect_business.add_argument("--package-dir", type=Path, required=True)
    inspect_business.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("manifest", type=Path)
    hydrate = sub.add_parser("hydrate-published")
    hydrate.add_argument("--manifest", type=Path, required=True)
    hydrate.add_argument("--published-versions", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        payload = build_release_set(
            args.project.resolve(), args.output.resolve(),
            require_fresh=not args.no_fresh,
            package_dir=args.package_dir.resolve(),
        )
    elif args.command == "inspect-business":
        payload = inspect_business_variants(
            args.package_dir.resolve(),
            output=args.output.resolve(),
        )
    elif args.command == "hydrate-published":
        payload = hydrate_published_artifacts(
            args.manifest.resolve(),
            args.published_versions.resolve(),
        )
    else:
        payload = verify_release_set(args.manifest.resolve())
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
