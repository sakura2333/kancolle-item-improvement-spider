from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from automation.common.bundle import verify_manifest
from automation.release.generated_state import verify_generated_state
from automation.release.npm_release_set import verify_release_set

PROJECT_ID = "kancolle-item-improvement-spider"


def current_commit(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def verify(root: Path, candidate: Path) -> dict:
    payload = verify_manifest(candidate, expected_kind="build-candidate", expected_project=PROJECT_ID)
    if payload.get("commit") != current_commit(root):
        raise RuntimeError("candidate commit does not match checked-out main commit")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict) or not metadata.get("sourceBundleContentHash"):
        raise RuntimeError("candidate is not bound to a source bundle")
    source_manifest_rel = metadata.get("sourceBundleManifest")
    if not isinstance(source_manifest_rel, str):
        raise RuntimeError("candidate lacks the frozen source bundle manifest")
    source_manifest_path = candidate / source_manifest_rel
    if not source_manifest_path.is_file():
        raise RuntimeError("candidate source bundle manifest is missing")
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if (
        source_manifest.get("kind") != "source-bundle"
        or source_manifest.get("projectId") != PROJECT_ID
        or source_manifest.get("commit") != payload.get("commit")
        or source_manifest.get("contentHash") != metadata.get("sourceBundleContentHash")
    ):
        raise RuntimeError("candidate source bundle binding is inconsistent")

    package = candidate / "dist/packages/kancolle-data/package.json"
    manifest = candidate / "dist/packages/kancolle-data/manifest.json"
    verification = candidate / str(metadata.get("verificationReport", "verification-report.json"))
    release_plan = candidate / str(metadata.get("releasePlan", "release-plan.json"))
    for required in (package, manifest, verification, release_plan):
        if not required.is_file():
            raise RuntimeError(f"candidate is missing required file: {required.relative_to(candidate)}")

    package_json = json.loads(package.read_text(encoding="utf-8"))
    manifest_json = json.loads(manifest.read_text(encoding="utf-8"))
    plan_json = json.loads(release_plan.read_text(encoding="utf-8"))
    if package_json.get("version") != manifest_json.get("packageVersion"):
        raise RuntimeError("candidate npm version mismatch")

    publication: dict = {"shouldPublish": bool(plan_json.get("shouldPublish"))}
    if publication["shouldPublish"]:
        release_set_rel = metadata.get("npmReleaseSet")
        online_manifest_rel = metadata.get("onlineState")
        if not isinstance(release_set_rel, str) or not isinstance(online_manifest_rel, str):
            raise RuntimeError("publishable candidate lacks frozen publication artifacts")
        release_set_path = candidate / release_set_rel
        online_root = candidate / Path(online_manifest_rel).parents[1]
        release_set = verify_release_set(release_set_path)
        online = verify_generated_state(online_root)
        current = next(
            (item for item in release_set["artifacts"] if item.get("variant") == "current"),
            None,
        )
        if not current or current.get("version") != package_json.get("version"):
            raise RuntimeError("frozen npm release-set does not match candidate package version")
        publication.update({"npmReleaseSet": release_set, "onlineState": online})

    return {
        "schemaVersion": 1,
        "candidate": payload,
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
