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
    AKASHI_URL,
    KC3_BONUS_URL,
    KCWIKI_EQUIPMENT_URL,
    KCWIKI_SHIP_URL,
    WIKIWIKI_URL,
    collect_akashi_source_records,
    prefetch_source,
)
from service.data_package.acquisition_references import QUEST_DATA_URL
from service.data_package.official_assets import acquire_required_assets
from util.http_cache import storage
from util.start2.start2_utils import update_start2_if_needed

PROJECT_ID = "kancolle-item-improvement-spider"

_REQUIRED_PREFETCH_SOURCES = (
    ("wikiwiki-index", WIKIWIKI_URL, True),
    ("kc3-bonus", KC3_BONUS_URL, True),
    ("kcquests-catalog", QUEST_DATA_URL, True),
)
_OPTIONAL_PREFETCH_SOURCES = (
    ("kcwiki-equipment", KCWIKI_EQUIPMENT_URL, False),
    ("kcwiki-ship", KCWIKI_SHIP_URL, False),
)
_REQUIRED_BUILD_CACHE_SOURCES = (
    ("akashi-list-index", AKASHI_URL),
    *((name, url) for name, url, _fresh in _REQUIRED_PREFETCH_SOURCES),
)


_RETIRED_USEITEM_CACHE_PREFIX = "cache/useitem/"
_RETIRED_EQUIPMENT_CACHE_PREFIX = "cache/equip/"


def prune_retired_image_cache(root: Path) -> dict[str, int]:
    """Remove the retired Akashi image cache without touching official assets.

    Seed bundles created before the official-assets migration can contain
    ``cache/useitem/*.png`` and ``cache/equip/*.png``. Those files are not
    valid inputs for the new package projections and should not be carried
    into the next immutable Source Bundle.
    """

    cache_root = root / ".spider/local/source-cache"
    removed_files = 0

    retired_useitem = cache_root / "cache/useitem"
    if retired_useitem.exists():
        removed_files += sum(1 for path in retired_useitem.rglob("*") if path.is_file())
        shutil.rmtree(retired_useitem)

    retired_equip = cache_root / "cache/equip"
    if retired_equip.exists():
        removed_files += sum(1 for path in retired_equip.rglob("*") if path.is_file())
        shutil.rmtree(retired_equip)

    removed_metadata = 0
    meta_path = cache_root / "_meta.json"
    if meta_path.is_file():
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            filtered = {}
            for key, value in payload.items():
                retired = key.startswith(_RETIRED_USEITEM_CACHE_PREFIX) or key.startswith(
                    _RETIRED_EQUIPMENT_CACHE_PREFIX
                )
                if retired:
                    removed_metadata += 1
                else:
                    filtered[key] = value
            if removed_metadata:
                meta_path.write_text(
                    json.dumps(
                        filtered, ensure_ascii=False, indent=2, sort_keys=True
                    )
                    + "\n",
                    encoding="utf-8",
                )

    return {
        "removedFiles": removed_files,
        "removedMetadata": removed_metadata,
    }


def _git_commit(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
    )
    return completed.stdout.strip()


def verify_build_cache_closure() -> dict[str, str]:
    """Reject a Source Bundle unless every fixed strict-Build input is sealed."""

    ready: dict[str, str] = {}
    for name, url in _REQUIRED_BUILD_CACHE_SOURCES:
        path = storage.url_to_path(url)
        storage.require_cached_file(path, url)
        meta = storage.load_meta(path)
        if (
            meta.get("url") != url
            or meta.get("fetch_status") != "fresh"
            or bool(meta.get("used_cache_fallback"))
        ):
            raise RuntimeError(
                f"required Build source cache is not freshly validated: {name}: {url}"
            )
        ready[name] = storage.cache_key(path)
    return ready


def acquire_non_wikiwiki_sources() -> dict:
    update_start2_if_needed()
    # Parsing detail pages here is limited to business-source discovery and raw
    # acquisition. Official image acquisition runs after canonical route parsing.
    records = collect_akashi_source_records()
    asset_summary = acquire_required_assets(records)
    statuses: dict[str, str] = {
        "start2": "ready",
        "akashi-list": f"ready:{len(records)}",
        "official-assets": (
            f"ready:{asset_summary['equipmentCount']}:{asset_summary['useitemCount']}"
        ),
    }
    for name, url, fresh in _REQUIRED_PREFETCH_SOURCES:
        prefetch_source(url, require_fresh=fresh)
        statuses[name] = "ready"
    for name, url, fresh in _OPTIONAL_PREFETCH_SOURCES:
        try:
            prefetch_source(url, require_fresh=fresh)
            statuses[name] = "ready"
        except Exception as exc:  # KCWiki remains non-blocking by contract.
            statuses[name] = f"unavailable:{type(exc).__name__}"
            print(
                f"\033[31m[KCWIKI RAW UNAVAILABLE][NON-BLOCKING] {name}: {exc}\033[0m",
                file=sys.stderr,
            )
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
    retired = prune_retired_image_cache(root)
    statuses = acquire_non_wikiwiki_sources()
    statuses["retired-image-cache"] = (
        f"pruned:{retired['removedFiles']}:{retired['removedMetadata']}"
    )
    run_wikiwiki(root, daily_limit=daily_limit)
    closure = verify_build_cache_closure()
    statuses["build-cache-closure"] = f"ready:{len(closure)}"
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
