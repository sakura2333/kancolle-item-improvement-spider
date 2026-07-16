from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from automation.common.bundle import (
    copy_tree,
    sha256_file,
    verify_manifest,
    verify_ready_lock,
    write_manifest,
)

PROJECT_ID = "kancolle-item-improvement-spider"
_FROZEN_COMPLETED_COLLECTIONS = ("akashi-list",)
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SOURCE_ARTIFACT_NAME = "kancolle-source-bundle"


def _git_commit(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def _positive_int(value: object, *, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} must be a positive integer") from exc
    if result <= 0:
        raise RuntimeError(f"{label} must be a positive integer")
    return result


def load_source_selection(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"source selection is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise RuntimeError("source selection schema is invalid")
    if payload.get("workflow") != "source-acquire.yml":
        raise RuntimeError("source selection workflow is invalid")
    workflow_run_id = _positive_int(payload.get("workflowRunId"), label="workflowRunId")
    run_attempt = _positive_int(payload.get("runAttempt"), label="runAttempt")
    artifact_id = _positive_int(payload.get("artifactId"), label="artifactId")
    artifact_name = str(payload.get("artifactName") or "")
    if artifact_name != _SOURCE_ARTIFACT_NAME:
        raise RuntimeError("source selection artifactName is invalid")
    artifact_digest = str(payload.get("artifactDigest") or "").lower()
    if not _SHA256_RE.fullmatch(artifact_digest):
        raise RuntimeError("source selection artifactDigest is invalid")
    source_head_sha = str(payload.get("sourceHeadSha") or "").lower()
    if not _COMMIT_RE.fullmatch(source_head_sha):
        raise RuntimeError("source selection sourceHeadSha is invalid")
    expected_keys = {
        "schemaVersion",
        "workflow",
        "workflowRunId",
        "runAttempt",
        "artifactId",
        "artifactName",
        "artifactDigest",
        "sourceHeadSha",
    }
    if set(payload) != expected_keys:
        raise RuntimeError("source selection fields are invalid")
    return {
        "schemaVersion": 1,
        "workflow": "source-acquire.yml",
        "workflowRunId": workflow_run_id,
        "runAttempt": run_attempt,
        "artifactId": artifact_id,
        "artifactName": artifact_name,
        "artifactDigest": artifact_digest,
        "sourceHeadSha": source_head_sha,
    }


def restore_source_bundle(root: Path, bundle: Path) -> dict:
    manifest = verify_manifest(bundle, expected_kind="source-bundle", expected_project=PROJECT_ID)
    lock = verify_ready_lock(bundle, manifest)
    for relative in (
        ".spider/local/source-cache",
        ".spider/local/wikiwiki-crawler",
        "dist/data-pipeline/start2_data",
    ):
        target = root / relative
        if target.exists():
            shutil.rmtree(target)
        copy_tree(bundle / relative, target)
    manifest["readyLock"] = lock
    return manifest


def _trust_frozen_source_bundle(root: Path, source: dict) -> None:
    from util.http_cache import audit

    meta_path = root / ".spider/local/source-cache/_meta.json"
    if meta_path.is_file():
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("source cache metadata is invalid")
        for item in payload.values():
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if (
                isinstance(url, str)
                and url
                and item.get("fetch_status") == "fresh"
                and not item.get("used_cache_fallback")
            ):
                audit.mark_validated(url)
    for collection in _FROZEN_COMPLETED_COLLECTIONS:
        audit.mark_collection_completed(collection)


def prepare(root: Path, bundle: Path, *, source_selection: Path | None = None) -> dict:
    selection = load_source_selection(source_selection) if source_selection else None
    source = restore_source_bundle(root, bundle)
    if selection and source.get("commit") != selection["sourceHeadSha"]:
        raise RuntimeError("source bundle acquisition commit does not match selected artifact run")
    os.environ["CACHE_ONLY"] = "1"
    os.environ["DATA_PACKAGE_STRICT"] = "1"
    os.environ["VALIDATION_STRICT"] = "1"
    _trust_frozen_source_bundle(root, source)
    # Import after CACHE_ONLY is set because configs.config is intentionally a
    # process-level immutable runtime configuration.
    from service.akashi_list.akashi_list_spider import process

    process()
    return {"sourceBundle": source, "sourceSelection": selection}


def _package_metadata(output: Path, npm_release_set: Path | None) -> dict:
    package_path = output / "dist/packages/kancolle-data/package.json"
    if not package_path.is_file():
        raise RuntimeError("build candidate package.json is missing")
    package_json = json.loads(package_path.read_text(encoding="utf-8"))
    package = {
        "name": str(package_json.get("name") or ""),
        "version": str(package_json.get("version") or ""),
        "artifacts": [],
    }
    if not package["name"] or not package["version"]:
        raise RuntimeError("build candidate package identity is incomplete")
    if npm_release_set is not None:
        manifest_path = npm_release_set / "release-set.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            raise RuntimeError("npm release-set artifacts are invalid")
        for item in artifacts:
            if not isinstance(item, dict):
                raise RuntimeError("npm release-set artifact is invalid")
            package["artifacts"].append(
                {
                    "variant": str(item.get("variant") or ""),
                    "version": str(item.get("version") or ""),
                    "distTag": str(item.get("distTag") or ""),
                    "tgzSha256": f"sha256:{str(item.get('sha256') or '').removeprefix('sha256:')}",
                }
            )
    return package


def _freeze_source_evidence(
    output: Path,
    source_bundle: Path,
    source_selection: dict,
) -> tuple[dict, dict]:
    source_manifest = verify_manifest(
        source_bundle,
        expected_kind="source-bundle",
        expected_project=PROJECT_ID,
    )
    source_lock = verify_ready_lock(source_bundle, source_manifest)
    if source_manifest.get("commit") != source_selection["sourceHeadSha"]:
        raise RuntimeError("source bundle commit does not match source selection")

    manifest_source = source_bundle / "bundle-manifest.json"
    lock_source = source_bundle / "source-bundle.lock.json"
    manifest_target = output / "source-bundle-manifest.json"
    lock_target = output / "source-bundle-ready-lock.json"
    shutil.copy2(manifest_source, manifest_target)
    shutil.copy2(lock_source, lock_target)

    source = {
        "workflow": source_selection["workflow"],
        "workflowRunId": source_selection["workflowRunId"],
        "runAttempt": source_selection["runAttempt"],
        "artifactId": source_selection["artifactId"],
        "artifactName": source_selection["artifactName"],
        "artifactDigest": source_selection["artifactDigest"],
        "sourceHeadSha": source_selection["sourceHeadSha"],
        "acquisitionCommit": source_manifest.get("commit"),
        "contentHash": source_manifest.get("contentHash"),
        "manifest": "source-bundle-manifest.json",
        "manifestSha256": f"sha256:{sha256_file(manifest_target)}",
        "readyLock": "source-bundle-ready-lock.json",
        "readyLockSha256": f"sha256:{sha256_file(lock_target)}",
    }
    return source_manifest, source


def freeze(
    root: Path,
    output: Path,
    *,
    source_bundle: Path | None = None,
    source_selection: dict | None = None,
    source_manifest: dict | None = None,
    release_plan: Path | None = None,
    verification_report: Path | None = None,
    npm_release_set: Path | None = None,
    online_state: Path | None = None,
) -> dict:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    copy_tree(root / "dist/data-pipeline", output / "dist/data-pipeline")
    copy_tree(root / "dist/packages/kancolle-data", output / "dist/packages/kancolle-data")

    commit = _git_commit(root)
    metadata: dict = {"code": {"githubSha": commit}}
    if source_bundle is not None:
        if source_selection is None:
            raise RuntimeError("source selection is required when freezing a source bundle")
        frozen_manifest, frozen_source = _freeze_source_evidence(
            output,
            source_bundle,
            source_selection,
        )
        metadata["source"] = frozen_source
        # Preserve the original public keys for compatibility with older readers.
        metadata["sourceBundleManifest"] = frozen_source["manifest"]
        metadata["sourceBundleContentHash"] = frozen_manifest.get("contentHash")
    elif source_manifest:
        source_manifest_path = output / "source-bundle-manifest.json"
        source_manifest_path.write_text(
            json.dumps(source_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        metadata["sourceBundleManifest"] = "source-bundle-manifest.json"
        metadata["sourceBundleContentHash"] = source_manifest.get("contentHash")

    if release_plan is not None:
        target = output / "release-plan.json"
        shutil.copy2(release_plan, target)
        metadata["releasePlan"] = "release-plan.json"
    if verification_report is not None:
        target = output / "verification-report.json"
        shutil.copy2(verification_report, target)
        metadata["verificationReport"] = "verification-report.json"
    if npm_release_set is not None:
        copy_tree(npm_release_set, output / "npm-release-set")
        metadata["npmReleaseSet"] = "npm-release-set/release-set.json"
    if online_state is not None:
        copy_tree(online_state, output / "online-state")
        metadata["onlineState"] = "online-state/.generated-state/manifest.json"

    metadata["package"] = _package_metadata(output, npm_release_set)
    return write_manifest(
        output,
        kind="build-candidate",
        project_id=PROJECT_ID,
        commit=commit,
        metadata=metadata,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a data candidate from frozen source evidence")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--project", type=Path, default=Path.cwd())
    prepare_parser.add_argument("--source-bundle", type=Path, required=True)
    prepare_parser.add_argument("--source-selection", type=Path)
    freeze_parser = sub.add_parser("freeze")
    freeze_parser.add_argument("--project", type=Path, default=Path.cwd())
    freeze_parser.add_argument("--output", type=Path, required=True)
    freeze_parser.add_argument("--source-bundle", type=Path)
    freeze_parser.add_argument("--source-selection", type=Path)
    freeze_parser.add_argument("--release-plan", type=Path)
    freeze_parser.add_argument("--verification-report", type=Path)
    freeze_parser.add_argument("--npm-release-set", type=Path)
    freeze_parser.add_argument("--online-state", type=Path)
    args = parser.parse_args()
    root = args.project.resolve()
    if args.command == "prepare":
        payload = prepare(
            root,
            args.source_bundle.resolve(),
            source_selection=args.source_selection.resolve() if args.source_selection else None,
        )
    else:
        selection = (
            load_source_selection(args.source_selection.resolve())
            if args.source_selection
            else None
        )
        payload = freeze(
            root,
            args.output.resolve(),
            source_bundle=args.source_bundle.resolve() if args.source_bundle else None,
            source_selection=selection,
            release_plan=args.release_plan.resolve() if args.release_plan else None,
            verification_report=args.verification_report.resolve() if args.verification_report else None,
            npm_release_set=args.npm_release_set.resolve() if args.npm_release_set else None,
            online_state=args.online_state.resolve() if args.online_state else None,
        )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
