from __future__ import annotations

"""Project-owned npm release variants for Stable main.

The canonical package is published to ``latest``.  A second package version is
built from the same candidate by projecting the frozen schema-3 improvement VO
onto the package's normal public paths; that version is published under the
``improvement2`` dist-tag so the legacy plugin does not need a path change.
"""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
from typing import Any

try:  # imported as script.project.*
    from ._common import (
        ProjectCommandError,
        parse_json_output,
        project_env,
        run,
        sha256_file,
        write_json,
    )
except ImportError:  # executed with script/project on sys.path
    from _common import (  # type: ignore
        ProjectCommandError,
        parse_json_output,
        project_env,
        run,
        sha256_file,
        write_json,
    )


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
    run(["npm", "run", "check"], cwd=package_dir, env=project_env())
    if require_fresh:
        run(["npm", "run", "check:fresh"], cwd=package_dir, env=project_env())
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
        env=project_env(),
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
        "tarball": str(tarball.resolve()),
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
    compat_dataset = compat.get("datasets", {}).get("improvement", {})
    if compat.get("consumer") != IMPROVEMENT2_CONSUMER:
        raise ProjectCommandError("improvement2 compatibility manifest consumer mismatch")
    if compat_dataset.get("schemaVersion") != 3 or compat_dataset.get("listSchemaVersion") != 2:
        raise ProjectCommandError("improvement2 compatibility manifest is not schema 3/list schema 2")

    result = deepcopy(canonical)
    result.pop("compatibility", None)
    result["packageVersion"] = compat_version
    improvement = deepcopy(result["datasets"]["improvement"])
    for key in _SCHEMA4_ONLY_IMPROVEMENT_METADATA:
        improvement.pop(key, None)
    improvement.update(
        {
            "schemaVersion": 3,
            "listSchemaVersion": 2,
            "list": "improvement/list.json",
            "detail": "improvement/detail.nedb",
            "detailRecordCount": compat_dataset.get("detailRecordCount"),
            "routeCount": compat_dataset.get("routeCount"),
        }
    )
    result["datasets"]["improvement"] = improvement
    return result


def _build_improvement2_staging(source_package: Path, staging: Path) -> str:
    shutil.copytree(
        source_package,
        staging,
        ignore=shutil.ignore_patterns("node_modules", "*.tgz", ".DS_Store"),
    )
    package_json_path = staging / "package.json"
    package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
    if package_json.get("name") != PACKAGE_NAME:
        raise ProjectCommandError("unexpected npm package name for improvement2 projection")
    compat_version = improvement2_version(str(package_json["version"]))
    package_json["version"] = compat_version
    package_json["description"] = (
        "Frozen schema-3 compatibility projection for poi-plugin-item-improvement2, "
        "generated by kancolle-item-improvement-spider"
    )
    package_json["scripts"]["check"] = (
        "node -e \"const d=require('./');const fs=require('fs');"
        "const m=JSON.parse(fs.readFileSync(d.manifestPath));"
        "for(const p of [d.manifestPath,d.releasesPath,d.improvement.listPath,"
        "d.improvement.detailPath,d.equipment.dropFromPath,d.equipment.sourcesPath,"
        "d.equipment.specialBonusesPath,d.schemas.improvementDetailPath,"
        "d.schemas.equipmentSourcesPath])if(!fs.existsSync(p))throw new Error('missing '+p);"
        "if(m.datasets.improvement.schemaVersion!==3)throw new Error('unexpected improvement schema');"
        "if(m.datasets.improvement.listSchemaVersion!==2)throw new Error('unexpected list schema');"
        "if(m.datasets.equipmentSources.schemaVersion!==1)throw new Error('unexpected equipment sources schema');"
        "if(m.datasets.equipmentSpecialBonuses.schemaVersion!==2)throw new Error('unexpected special bonus schema');"
        "if((m.datasets.useitemIcons.missingIds||[]).length)throw new Error('missing useitem icons');"
        "for(const id of m.datasets.useitemIcons.requiredIds||[])"
        "if(!fs.existsSync(d.assets.useitemPath(id)))throw new Error('missing icon '+id)\""
    )
    package_json_path.write_text(
        json.dumps(package_json, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    compat_root = staging / "compat" / IMPROVEMENT2_CONSUMER
    shutil.copy2(compat_root / "improvement" / "list.json", staging / "improvement" / "list.json")
    shutil.copy2(compat_root / "improvement" / "detail.nedb", staging / "improvement" / "detail.nedb")
    shutil.copy2(
        staging / "schemas" / "improvement-detail-v3.schema.json",
        staging / "schemas" / "improvement-detail.schema.json",
    )
    shutil.rmtree(staging / "compat")
    (staging / "schemas" / "improvement-detail-v3.schema.json").unlink(missing_ok=True)

    readme = staging / "README.md"
    readme.write_text(
        "# Improvement2 compatibility distribution\n\n"
        "This npm version freezes the schema-3 improvement value object on the normal "
        "`improvement/*` paths for `poi-plugin-item-improvement2`. It is generated from "
        "the same canonical Spider release and is selected through the `improvement2` "
        "dist-tag.\n\n"
        + readme.read_text(encoding="utf-8"),
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


def _verify_tarball(result: dict[str, Any], *, schema_version: int, compatibility: bool) -> None:
    tarball = Path(str(result["tarball"]))
    with tarfile.open(tarball, "r:gz") as archive:
        names = set(archive.getnames())
        package_json = _tar_member_json(archive, "package/package.json")
        manifest = _tar_member_json(archive, "package/manifest.json")
        if package_json.get("name") != PACKAGE_NAME or package_json.get("version") != result["version"]:
            raise ProjectCommandError("npm tarball identity mismatch")
        if manifest.get("packageVersion") != result["version"]:
            raise ProjectCommandError("npm tarball manifest version mismatch")
        if manifest.get("datasets", {}).get("improvement", {}).get("schemaVersion") != schema_version:
            raise ProjectCommandError("npm tarball improvement schema mismatch")
        has_internal_compat = any(name.startswith("package/compat/") for name in names)
        if has_internal_compat:
            raise ProjectCommandError("published npm tarball leaked internal compatibility staging")
        if "package/schemas/improvement-detail-v3.schema.json" in names:
            raise ProjectCommandError("published npm tarball leaked the internal v3 schema filename")
        if compatibility:
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


def build_release_set(
    root: Path,
    output_dir: Path,
    *,
    require_fresh: bool = True,
) -> dict[str, Any]:
    package_dir = root / "packages" / "kancolle-data"
    output_dir = output_dir.resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    current = _package_result(package_dir, output_dir, require_fresh=require_fresh)
    write_json(output_dir / "current.package-result.json", current)

    with tempfile.TemporaryDirectory(prefix="kancolle-data-improvement2-") as temp_name:
        staging = Path(temp_name) / "package"
        compat_version = _build_improvement2_staging(package_dir, staging)
        compatibility = _package_result(staging, output_dir, require_fresh=require_fresh)
    if compatibility["version"] != compat_version:
        raise ProjectCommandError("improvement2 package version changed during packing")
    write_json(output_dir / "improvement2.package-result.json", compatibility)

    _verify_tarball(current, schema_version=4, compatibility=False)
    _verify_tarball(compatibility, schema_version=3, compatibility=True)

    release_set = {
        "schemaVersion": 1,
        "package": PACKAGE_NAME,
        "policy": "stable-main-with-frozen-improvement2-projection",
        "publishMode": "manual-npm-auth-then-flow-reconcile",
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
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 2:
        raise ProjectCommandError("npm release-set must contain current and improvement2 artifacts")
    expected = {"current": (CURRENT_TAG, 4), "improvement2": (IMPROVEMENT2_TAG, 3)}
    seen: set[str] = set()
    for artifact in artifacts:
        variant = artifact.get("variant")
        if variant not in expected or variant in seen:
            raise ProjectCommandError("npm release-set contains an unknown or duplicate variant")
        seen.add(variant)
        tag, schema = expected[variant]
        if artifact.get("distTag") != tag:
            raise ProjectCommandError(f"npm release-set variant {variant} has an invalid dist-tag")
        tarball = Path(str(artifact.get("tarball", ""))).resolve()
        if not tarball.is_file() or sha256_file(tarball) != artifact.get("sha256"):
            raise ProjectCommandError(f"npm release-set variant {variant} tarball identity mismatch")
        _verify_tarball(artifact, schema_version=schema, compatibility=variant == "improvement2")
    return payload
