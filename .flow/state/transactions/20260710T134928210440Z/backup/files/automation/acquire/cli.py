from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from automation.common.bundle import copy_tree, write_manifest
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


def run_wikiwiki(root: Path, *, daily_limit: int) -> None:
    local = root / "configs/wikiwiki-crawler.local.json"
    if not local.exists():
        shutil.copy2(root / "configs/wikiwiki-crawler.default.json", local)
    crawler = root / "automation/acquire/wikiwiki/crawler.py"
    start2 = root / "dist/data-pipeline/start2_data/api_mst_slotitem.json"
    common = [sys.executable, str(crawler), "--project", str(root)]
    subprocess.run(
        [*common, "catalog", "--start2", str(start2), "--kind", "all", "--refresh"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        [*common, "crawl", "--start2", str(start2), "--daily-limit", str(daily_limit)],
        cwd=root,
        check=True,
    )
    receipt = root / ".flow/local/wikiwiki-crawler/source-receipt.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    if payload.get("ready") is not True:
        raise RuntimeError("WikiWiki source receipt is not ready")


def build_bundle(root: Path, output: Path, *, daily_limit: int) -> dict:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    statuses = acquire_non_wikiwiki_sources()
    run_wikiwiki(root, daily_limit=daily_limit)
    copy_tree(root / ".flow/local/source-cache", output / ".flow/local/source-cache")
    copy_tree(root / ".flow/local/wikiwiki-crawler", output / ".flow/local/wikiwiki-crawler")
    copy_tree(root / "dist/data-pipeline/start2_data", output / "dist/data-pipeline/start2_data")
    return write_manifest(
        output,
        kind="source-bundle",
        project_id=PROJECT_ID,
        commit=_git_commit(root),
        metadata={"sources": statuses},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire immutable Spider source evidence")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wikiwiki-daily-limit", type=int, default=10000)
    args = parser.parse_args()
    payload = build_bundle(args.project.resolve(), args.output.resolve(), daily_limit=args.wikiwiki_daily_limit)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
