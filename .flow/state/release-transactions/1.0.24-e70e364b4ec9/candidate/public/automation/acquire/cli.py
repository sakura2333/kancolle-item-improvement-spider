from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from automation.common.bundle import (
    copy_tree,
    verify_manifest,
    verify_ready_lock,
    write_manifest,
    write_ready_lock,
)
from service.akashi_list.akashi_list_spider import (
    KC3_BONUS_URL,
    KCWIKI_EQUIPMENT_URL,
    KCWIKI_SHIP_URL,
    WIKIWIKI_URL,
    collect_akashi_source_records,
    prefetch_source,
)
from util.start2.start2_utils import update_start2_if_needed

PROJECT_ID = "kancolle-item-improvement-spider"


def _git_commit(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
    )
    return completed.stdout.strip()


def acquire_non_wikiwiki_sources() -> dict:
    update_start2_if_needed()
    # Parsing detail pages here is limited to source discovery and image/raw
    # acquisition. No canonical projection or npm package is written.
    records = collect_akashi_source_records()
    statuses: dict[str, str] = {"start2": "ready", "akashi-list": f"ready:{len(records)}"}
    for name, url, fresh in (
        ("wikiwiki-index", WIKIWIKI_URL, True),
        ("kcwiki-equipment", KCWIKI_EQUIPMENT_URL, False),
        ("kcwiki-ship", KCWIKI_SHIP_URL, False),
        ("kc3-bonus", KC3_BONUS_URL, True),
    ):
        try:
            prefetch_source(url, require_fresh=fresh)
            statuses[name] = "ready"
        except Exception as exc:  # KCWiki remains non-blocking by contract.
            if name.startswith("kcwiki-"):
                statuses[name] = f"unavailable:{type(exc).__name__}"
                print(
                    f"\033[31m[KCWIKI RAW UNAVAILABLE][NON-BLOCKING] {name}: {exc}\033[0m",
                    file=sys.stderr,
                )
            else:
                raise
    return statuses


def restore_seed_bundle(root: Path, bundle: Path) -> dict:
    manifest = verify_manifest(bundle, expected_kind="source-bundle", expected_project=PROJECT_ID)
    verify_ready_lock(bundle, manifest)
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


def run_wikiwiki(root: Path, *, daily_limit: int) -> None:
    local = root / "configs/wikiwiki-crawler.local.json"
    if not local.exists():
        shutil.copy2(root / "configs/wikiwiki-crawler.default.json", local)
    crawler = root / "automation/acquire/wikiwiki/crawler.py"
    start2 = root / "dist/data-pipeline/start2_data/api_mst_slotitem.json"
    common = [sys.executable, str(crawler), "--project", str(root)]
    subprocess.run(
        [*common, "catalog", "--start2", str(start2), "--kind", "all"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        [*common, "crawl", "--start2", str(start2), "--daily-limit", str(daily_limit)],
        cwd=root,
        check=True,
    )
    receipt = root / ".spider/local/wikiwiki-crawler/source-receipt.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    if payload.get("ready") is not True:
        raise RuntimeError("WikiWiki source receipt is not ready")


def build_bundle(
    root: Path, output: Path, *, daily_limit: int, seed_bundle: Path | None = None
) -> dict:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    if seed_bundle is not None:
        restore_seed_bundle(root, seed_bundle)
    statuses = acquire_non_wikiwiki_sources()
    run_wikiwiki(root, daily_limit=daily_limit)
    copy_tree(root / ".spider/local/source-cache", output / ".spider/local/source-cache")
    copy_tree(root / ".spider/local/wikiwiki-crawler", output / ".spider/local/wikiwiki-crawler")
    copy_tree(root / "dist/data-pipeline/start2_data", output / "dist/data-pipeline/start2_data")
    manifest = write_manifest(
        output,
        kind="source-bundle",
        project_id=PROJECT_ID,
        commit=_git_commit(root),
        metadata={"sources": statuses},
    )
    write_ready_lock(output, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire immutable Spider source evidence")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wikiwiki-daily-limit", type=int, default=10000)
    parser.add_argument("--seed-bundle", type=Path)
    args = parser.parse_args()
    payload = build_bundle(
        args.project.resolve(),
        args.output.resolve(),
        daily_limit=args.wikiwiki_daily_limit,
        seed_bundle=args.seed_bundle.resolve() if args.seed_bundle else None,
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
