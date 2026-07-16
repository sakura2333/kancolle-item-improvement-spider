#!/usr/bin/env python3
from __future__ import annotations

"""Akashi List source acquisition worker.

This command is a source-acquisition boundary.  It downloads/parses Akashi List
inside one isolated process and writes a receipt for Flow to join later.  It does
not export the public data package; local processing still happens after all
source workers finish.
"""

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lxml import etree

from service.akashi_list.akashi_detail_processor import DetailProcessor
from service.akashi_list.akashi_list_utils import convert_vo
from service.akashi_list.akashi_list_spider import AKASHI_URL
from util.cache import fetch, get_fetch_meta, mark_collection_completed
from util.start2.start2_utils import update_start2_if_needed

RECEIPT_PATH = PROJECT_ROOT / ".spider" / "local" / "source-receipts" / "akashi-list.json"
PAYLOAD_PATH = PROJECT_ROOT / ".spider" / "local" / "source-cache" / "akashi-list" / "vo.json"


def _json_clean(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "to_json"):
        return _json_clean(value.to_json())
    if is_dataclass(value):
        return _json_clean(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_clean(item) for item in value]
    return value


def _fetch_summary(url: str) -> dict:
    meta = get_fetch_meta(url)
    return {
        "url": url,
        "status": meta.get("fetch_status", "unknown"),
        "statusCode": meta.get("status_code"),
        "validatedAt": meta.get("validated_at"),
        "validatedInRun": bool(meta.get("validated_in_run")),
        "usedCacheFallback": bool(meta.get("used_cache_fallback")),
        "contentSha256": meta.get("content_sha256"),
        "cachePath": meta.get("cache_path"),
    }


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _collect_akashi(detail_limit: int | None) -> tuple[list, dict]:
    page = fetch(AKASHI_URL)
    page_node = etree.HTML(page)
    weapon_list = page_node.xpath("//div[@id='weapon-remodel']/div")
    detail_processor = DetailProcessor()
    selected = 0
    skipped = 0
    detail_urls: list[str] = []
    for weapon in weapon_list:
        if weapon.xpath(".//div[@class='noremodel']"):
            skipped += 1
            continue
        if detail_limit is not None and selected >= detail_limit:
            break
        weapon_id = weapon.attrib["id"]
        url = f"https://akashi-list.me/detail/{weapon_id}.html"
        detail_page = fetch(url)
        detail_processor.process_detail_page(page=detail_page)
        detail_urls.append(url)
        selected += 1
        print(f"[akashi] id={weapon_id} status=saved", flush=True)
    vo_list = convert_vo(detail_processor.result)
    metadata = {
        "indexUrl": AKASHI_URL,
        "selected": selected,
        "skippedNoRemodelBeforeLimit": skipped,
        "detailLimit": detail_limit,
        "detailUrls": detail_urls,
        "indexFetch": _fetch_summary(AKASHI_URL),
        "detailFetches": [_fetch_summary(url) for url in detail_urls],
    }
    return vo_list, metadata


def _write_receipt(*, mode: str, ready: bool, vo_list: list, metadata: dict) -> None:
    payload = [_json_clean(item) for item in vo_list]
    _write_json_atomic(PAYLOAD_PATH, payload)
    receipt = {
        "schemaVersion": 1,
        "source": "akashi-list",
        "mode": mode,
        "ready": ready,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "payload": str(PAYLOAD_PATH.relative_to(PROJECT_ROOT)),
        "itemCount": len(payload),
        "scheduleCount": sum(len((item.get("improvementList") or [])) for item in payload if isinstance(item, dict)),
        "metadata": metadata,
    }
    _write_json_atomic(RECEIPT_PATH, receipt)
    print(
        "[akashi receipt] "
        f"ready={str(ready).lower()} mode={mode} items={receipt['itemCount']} "
        f"output={RECEIPT_PATH}",
        flush=True,
    )


def _usage(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    print("用法：python3 script/project/akashi_command.py [probe|full] [--daily-limit N] [--skip-start2]", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    action = values.pop(0) if values and not values[0].startswith("-") else "full"
    if action not in {"probe", "full"}:
        return _usage(f"未知 Akashi 命令：{action}")
    skip_start2 = False
    daily_limit: int | None = 3 if action == "probe" else None
    index = 0
    while index < len(values):
        item = values[index]
        if item == "--skip-start2":
            skip_start2 = True
        elif item == "--daily-limit":
            if index + 1 >= len(values):
                return _usage("--daily-limit 缺少数值")
            try:
                daily_limit = int(values[index + 1])
            except ValueError:
                return _usage("--daily-limit 必须是整数")
            if daily_limit < 0:
                return _usage("--daily-limit 必须大于等于 0")
            index += 1
        else:
            return _usage(f"未知参数：{item}")
        index += 1
    if action == "full" and daily_limit is not None:
        return _usage("full 不接受 --daily-limit；小样本请使用 probe")
    if not skip_start2:
        update_start2_if_needed()
    try:
        vo_list, metadata = _collect_akashi(daily_limit)
        ready = action == "full" and len(vo_list) > 0
        _write_receipt(mode=action, ready=ready, vo_list=vo_list, metadata=metadata)
        mark_collection_completed("akashi-list")
        if action == "probe":
            print("Akashi probe 已完成；这是小样本 source acquisition，不代表 full source ready", flush=True)
        return 0
    except Exception as exc:
        receipt = {
            "schemaVersion": 1,
            "source": "akashi-list",
            "mode": action,
            "ready": False,
            "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }
        _write_json_atomic(RECEIPT_PATH, receipt)
        print(f"ERROR: Akashi List source acquisition failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
