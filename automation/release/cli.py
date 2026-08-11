from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from automation.common.bundle import sha256_file, verify_manifest
from automation.release.generated_state import verify_generated_state
from automation.release.npm_release_set import verify_release_set

PROJECT_ID = "kancolle-item-improvement-spider"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def current_commit(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def _require_positive_int(value: object, *, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"candidate {label} is invalid") from exc
    if result <= 0:
        raise RuntimeError(f"candidate {label} is invalid")
    return result


def _verify_source_binding(candidate: Path, payload: dict, metadata: dict) -> dict:
    source = metadata.get("source")
    if not isinstance(source, dict):
        raise RuntimeError("candidate lacks immutable source artifact identity")
    required = {
        "workflow",
        "workflowRunId",
        "runAttempt",
        "artifactId",
        "artifactName",
        "artifactDigest",
        "sourceHeadSha",
        "acquisitionCommit",
        "contentHash",
        "manifest",
        "manifestSha256",
        "readyLock",
        "readyLockSha256",
    }
    if set(source) != required:
        raise RuntimeError("candidate source artifact identity fields are invalid")
    if source.get("workflow") != "source-acquire.yml":
        raise RuntimeError("candidate source workflow identity is invalid")
    _require_positive_int(source.get("workflowRunId"), label="source workflowRunId")
    _require_positive_int(source.get("runAttempt"), label="source runAttempt")
    _require_positive_int(source.get("artifactId"), label="source artifactId")
    if source.get("artifactName") != "kancolle-source-bundle":
        raise RuntimeError("candidate source artifact name is invalid")
    artifact_digest = str(source.get("artifactDigest") or "").lower()
    if not _SHA256_RE.fullmatch(artifact_digest):
        raise RuntimeError("candidate source artifact digest is invalid")
    for key in ("sourceHeadSha", "acquisitionCommit"):
        if not _COMMIT_RE.fullmatch(str(source.get(key) or "")):
            raise RuntimeError(f"candidate source {key} is invalid")
    if source.get("sourceHeadSha") != source.get("acquisitionCommit"):
        raise RuntimeError("candidate source run and acquisition commit are inconsistent")

    manifest_path = candidate / str(source.get("manifest") or "")
    lock_path = candidate / str(source.get("readyLock") or "")
    if not manifest_path.is_file() or not lock_path.is_file():
        raise RuntimeError("candidate frozen source manifest or ready lock is missing")
    if source.get("manifestSha256") != f"sha256:{sha256_file(manifest_path)}":
        raise RuntimeError("candidate frozen source manifest hash mismatch")
    if source.get("readyLockSha256") != f"sha256:{sha256_file(lock_path)}":
        raise RuntimeError("candidate frozen source ready-lock hash mismatch")

    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if (
        source_manifest.get("schemaVersion") != 1
        or source_manifest.get("kind") != "source-bundle"
        or source_manifest.get("projectId") != PROJECT_ID
        or source_manifest.get("commit") != source.get("acquisitionCommit")
        or source_manifest.get("contentHash") != source.get("contentHash")
    ):
        raise RuntimeError("candidate source bundle manifest binding is inconsistent")
    if source_lock.get("schemaVersion") != 1 or source_lock.get("status") != "ready":
        raise RuntimeError("candidate source ready lock is invalid")
    expected_lock = {
        "projectId": PROJECT_ID,
        "kind": "source-bundle",
        "commit": source_manifest.get("commit"),
        "contentHash": source_manifest.get("contentHash"),
        "manifestSha256": sha256_file(manifest_path),
    }
    for key, value in expected_lock.items():
        if source_lock.get(key) != value:
            raise RuntimeError(f"candidate source ready-lock mismatch: {key}")

    if metadata.get("sourceBundleManifest") != source.get("manifest"):
        raise RuntimeError("candidate legacy source manifest binding is inconsistent")
    if metadata.get("sourceBundleContentHash") != source.get("contentHash"):
        raise RuntimeError("candidate legacy source content binding is inconsistent")
    return source


def _verify_package_binding(
    candidate: Path,
    metadata: dict,
    package_json: dict,
    release_set: dict | None,
) -> dict:
    package = metadata.get("package")
    if not isinstance(package, dict):
        raise RuntimeError("candidate package identity is missing")
    if package.get("name") != package_json.get("name"):
        raise RuntimeError("candidate package name binding is inconsistent")
    if package.get("version") != package_json.get("version"):
        raise RuntimeError("candidate package version binding is inconsistent")
    declared = package.get("artifacts")
    if not isinstance(declared, list):
        raise RuntimeError("candidate package artifact identity is invalid")
    if release_set is None:
        if declared:
            raise RuntimeError("non-publish candidate unexpectedly declares npm tgz artifacts")
        return package

    expected: list[dict] = []
    for artifact in release_set.get("artifacts") or []:
        expected.append(
            {
                "variant": str(artifact.get("variant") or ""),
                "version": str(artifact.get("version") or ""),
                "distTag": str(artifact.get("distTag") or ""),
                "tgzSha256": f"sha256:{str(artifact.get('sha256') or '').removeprefix('sha256:')}",
            }
        )
    if declared != expected:
        raise RuntimeError("candidate package tgz identities do not match frozen release-set")
    return package


def verify(root: Path, candidate: Path) -> dict:
    payload = verify_manifest(candidate, expected_kind="build-candidate", expected_project=PROJECT_ID)
    checked_out = current_commit(root)
    if payload.get("commit") != checked_out:
        raise RuntimeError("candidate commit does not match checked-out main commit")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise RuntimeError("candidate metadata is invalid")
    code = metadata.get("code")
    if not isinstance(code, dict) or code != {"githubSha": payload.get("commit")}:
        raise RuntimeError("candidate code identity is inconsistent")
    source = _verify_source_binding(candidate, payload, metadata)

    package_path = candidate / "dist/packages/kancolle-data/package.json"
    manifest = candidate / "dist/packages/kancolle-data/manifest.json"
    verification = candidate / str(metadata.get("verificationReport", "verification-report.json"))
    release_plan = candidate / str(metadata.get("releasePlan", "release-plan.json"))
    for required in (package_path, manifest, verification, release_plan):
        if not required.is_file():
            raise RuntimeError(f"candidate is missing required file: {required.relative_to(candidate)}")

    package_json = json.loads(package_path.read_text(encoding="utf-8"))
    manifest_json = json.loads(manifest.read_text(encoding="utf-8"))
    plan_json = json.loads(release_plan.read_text(encoding="utf-8"))
    if package_json.get("version") != manifest_json.get("packageVersion"):
        raise RuntimeError("candidate npm version mismatch")

    publication: dict = {"shouldPublish": bool(plan_json.get("shouldPublish"))}
    release_set: dict | None = None
    if publication["shouldPublish"]:
        release_set_rel = metadata.get("npmReleaseSet")
        online_manifest_rel = metadata.get("onlineState")
        if not isinstance(release_set_rel, str) or not isinstance(online_manifest_rel, str):
            raise RuntimeError("publishable candidate lacks frozen publication artifacts")
        release_set_path = candidate / release_set_rel
        online_root = candidate / Path(online_manifest_rel).parents[1]
        release_set = verify_release_set(release_set_path)
        planned_business = plan_json.get("npmBusinessIdentities")
        if (
            not isinstance(planned_business, dict)
            or release_set.get("npmBusinessIdentities") != planned_business
        ):
            raise RuntimeError(
                "frozen npm release-set does not match the planned npm business content"
            )
        online = verify_generated_state(online_root)
        current = next(
            (item for item in release_set["artifacts"] if item.get("variant") == "current"),
            None,
        )
        if not current or current.get("version") != package_json.get("version"):
            raise RuntimeError("frozen npm release-set does not match candidate package version")
        publication.update({"npmReleaseSet": release_set, "onlineState": online})

    package = _verify_package_binding(candidate, metadata, package_json, release_set)
    return {
        "schemaVersion": 1,
        "candidate": payload,
        "code": code,
        "source": source,
        "package": package,
        "packageVersion": package_json.get("version"),
        "publication": publication,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a frozen candidate before external publication")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    payload = verify(args.project.resolve(), args.candidate.resolve())
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
