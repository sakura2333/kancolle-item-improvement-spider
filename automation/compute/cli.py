from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from automation.common.bundle import copy_tree, verify_manifest, write_manifest

PROJECT_ID = "kancolle-item-improvement-spider"


def _git_commit(root: Path) -> str:
    completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True)
    return completed.stdout.strip()


def restore_source_bundle(root: Path, bundle: Path) -> dict:
    manifest = verify_manifest(bundle, expected_kind="source-bundle", expected_project=PROJECT_ID)
    if manifest.get("commit") != _git_commit(root):
        raise RuntimeError("source bundle commit does not match checked-out main commit")
    for relative in (
        ".spider/local/source-cache",
        ".spider/local/wikiwiki-crawler",
        "dist/data-pipeline/start2_data",
    ):
        target = root / relative
        if target.exists():
            shutil.rmtree(target)
        copy_tree(bundle / relative, target)
    return manifest


def prepare(root: Path, bundle: Path) -> dict:
    source = restore_source_bundle(root, bundle)
    os.environ["CACHE_ONLY"] = "1"
    os.environ["DATA_PACKAGE_STRICT"] = "1"
    os.environ["VALIDATION_STRICT"] = "1"
    # Import after CACHE_ONLY is set because configs.config is intentionally a
    # process-level immutable runtime configuration.
    from service.akashi_list.akashi_list_spider import process

    process()
    return source


def freeze(
    root: Path,
    output: Path,
    *,
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
    metadata: dict = {}
    if source_manifest:
        source_manifest_path = output / "source-bundle-manifest.json"
        source_manifest_path.write_text(
            json.dumps(source_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
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
    return write_manifest(
        output,
        kind="build-candidate",
        project_id=PROJECT_ID,
        commit=_git_commit(root),
        metadata=metadata,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a data candidate from frozen source evidence")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--project", type=Path, default=Path.cwd())
    prepare_parser.add_argument("--source-bundle", type=Path, required=True)
    freeze_parser = sub.add_parser("freeze")
    freeze_parser.add_argument("--project", type=Path, default=Path.cwd())
    freeze_parser.add_argument("--output", type=Path, required=True)
    freeze_parser.add_argument("--source-bundle", type=Path)
    freeze_parser.add_argument("--release-plan", type=Path)
    freeze_parser.add_argument("--verification-report", type=Path)
    freeze_parser.add_argument("--npm-release-set", type=Path)
    freeze_parser.add_argument("--online-state", type=Path)
    args = parser.parse_args()
    root = args.project.resolve()
    if args.command == "prepare":
        payload = prepare(root, args.source_bundle.resolve())
    else:
        source_manifest = None
        if args.source_bundle:
            source_manifest = verify_manifest(
                args.source_bundle.resolve(), expected_kind="source-bundle", expected_project=PROJECT_ID
            )
        payload = freeze(
            root,
            args.output.resolve(),
            source_manifest=source_manifest,
            release_plan=args.release_plan.resolve() if args.release_plan else None,
            verification_report=args.verification_report.resolve() if args.verification_report else None,
            npm_release_set=args.npm_release_set.resolve() if args.npm_release_set else None,
            online_state=args.online_state.resolve() if args.online_state else None,
        )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
