#!/usr/bin/env python3
from __future__ import annotations

"""Manual WikiWiki acquisition using a local browser-derived curl session.

This file is intentionally standalone and standard-library only.  It may read
exported project data, but it must not import project runtime modules.
"""

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .page_catalog import load_name_aliases, parse_card_catalog, resolve_name
    from .raw_cache import install_capture, read_meta_index, url_to_cache_path
except ImportError:  # direct script execution
    from page_catalog import load_name_aliases, parse_card_catalog, resolve_name
    from raw_cache import install_capture, read_meta_index, url_to_cache_path

SOURCE_BASE = "https://wikiwiki.jp/kancolle/"
DEFAULT_CONFIG = Path("configs/wikiwiki-crawler.local.json")
DEFAULT_CONFIG_BASE = Path("configs/wikiwiki-crawler.default.json")
DEFAULT_OUTPUT = Path(".spider/local/wikiwiki-crawler")
DEFAULT_RAW_ROOT = Path(".spider/local/source-cache")
DEFAULT_START2 = Path("dist/data-pipeline/start2_data/api_mst_slotitem.json")
DEFAULT_CATALOG = Path(".spider/local/wikiwiki-crawler/catalog/equipment-pages.json")
DEFAULT_CATALOG_DIR = Path(".spider/local/wikiwiki-crawler/catalog")
DEFAULT_SOURCE_RECEIPT = Path(".spider/local/wikiwiki-crawler/source-receipt.json")
DETAIL_ROLES = {
    "equipment": "required-detail-pages",
    "ship": "deferred-locator-only",
}
DEFAULT_NAME_ALIASES = Path("configs/wikiwiki-page-name-aliases.json")
CATALOG_SOURCES = {
    "equipment": "https://wikiwiki.jp/kancolle/%E8%A3%85%E5%82%99%E3%82%AB%E3%83%BC%E3%83%89%E4%B8%80%E8%A6%A7",
    "ship": "https://wikiwiki.jp/kancolle/%E8%89%A6%E5%A8%98%E3%82%AB%E3%83%BC%E3%83%89%E4%B8%80%E8%A6%A7",
    "improvement": "https://wikiwiki.jp/kancolle/%E6%94%B9%E4%BF%AE%E8%A1%A8",
}
CATALOG_ROLES = {
    "equipment": "locator-index",
    "ship": "locator-index",
    "improvement": "validation-index",
}
PAGE_ID_RE = re.compile(r"\bNo\.\s*0*([0-9]{1,4})\b", re.IGNORECASE)
CHALLENGE_MARKERS = (
    "<title>Just a moment...</title>",
    "cf-chl-",
    "challenge-platform",
    "Attention Required! | Cloudflare",
    "Enable JavaScript and cookies to continue",
)


class OperatorStop(RuntimeError):
    def __init__(
        self,
        stop_reason: str,
        message: str,
        action: str,
        checkpoint: str,
        *,
        details: dict[str, Any] | None = None,
        exit_code: int = 75,
    ) -> None:
        super().__init__(message)
        self.stop_reason = stop_reason
        self.message = message
        self.action = action
        self.checkpoint = checkpoint
        self.details = details or {}
        self.exit_code = exit_code

    def payload(self) -> dict[str, Any]:
        result = {
            "status": "operator-stop",
            "stopReason": self.stop_reason,
            "message": self.message,
            "action": self.action,
            "checkpoint": self.checkpoint,
            "exitCode": self.exit_code,
        }
        if self.details:
            result["details"] = self.details
        return result


def print_operator_stop(error: OperatorStop) -> None:
    prefix = "\033[31mERROR\033[0m" if sys.stderr.isatty() else "ERROR"
    print(f"{prefix}: {error.message}", file=sys.stderr)
    print(f"stopReason: {error.stop_reason}", file=sys.stderr)
    print(f"人工处理: {error.action}", file=sys.stderr)
    print(f"可继续断点: {error.checkpoint}", file=sys.stderr)
    if error.details:
        print(
            "details: " + json.dumps(error.details, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )


def apply_operator_stop(summary: dict[str, Any], error: OperatorStop) -> None:
    summary.update(error.payload())
    summary["operatorStop"] = error.payload()
    print_operator_stop(error)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, prefix=path.name + "."
    ) as handle:
        handle.write(encoded)
        temp = Path(handle.name)
    os.replace(temp, path)


def append_json_line(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_browser_session_config(path: Path) -> dict[str, Any]:
    try:
        local = read_json(path)
        base_path = path.parent / "wikiwiki-crawler.default.json"
        if base_path.is_file() and not base_path.samefile(path):
            base = read_json(base_path)
            if isinstance(base, dict) and isinstance(local, dict):
                merged = dict(base)
                merged.update(local)
                local = merged
        return validate_config(local)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise OperatorStop(
            "wikiwiki-session-config-invalid",
            f"WikiWiki Cookie/浏览器会话配置不可用：{exc}",
            "从当前浏览器重新导出可用 Cookie 和请求头，更新 configs/wikiwiki-crawler.local.json。",
            str(path),
        ) from exc


def validate_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("config must be a JSON object")

    result = dict(value)
    transport = str(result.get("transport") or "curl").strip().lower()
    if transport not in {"curl", "playwright"}:
        raise ValueError("config.transport must be 'curl' or 'playwright'")
    result["transport"] = transport

    required = ["userAgent", "acceptLanguage"]
    if transport == "curl":
        required.append("cookie")
    for key in required:
        if not isinstance(result.get(key), str) or not result[key].strip():
            raise ValueError(f"config.{key} must be a non-empty string")
    if "..." in result["userAgent"]:
        raise ValueError("config.userAgent still contains placeholder '...'")
    if transport == "curl" and "REPLACE_ME" in result["cookie"]:
        raise ValueError("config.cookie still contains REPLACE_ME")

    headers = result.get("headers", [])
    if headers is None:
        headers = []
    if not isinstance(headers, list) or any(not isinstance(item, str) for item in headers):
        raise ValueError("config.headers must be an array of strings")
    result["headers"] = headers

    browser_args = result.get("browserArgs", [])
    if browser_args is None:
        browser_args = []
    if not isinstance(browser_args, list) or any(not isinstance(item, str) for item in browser_args):
        raise ValueError("config.browserArgs must be an array of strings")
    result["browserArgs"] = browser_args

    defaults = {
        "delaySeconds": 3.0,
        "delayJitterSeconds": 1.0,
        "rateLimitCooldownSeconds": 90,
        "maxRateLimitRetries": 2,
        "maxConsecutiveRateLimits": 3,
        "transientRetrySeconds": 20,
        "maxTransientRetries": 2,
        "dailyLimit": 40,
        "maxAgeDays": 15,
        "catalogMaxAgeHours": 360,
        "curlPath": "curl",
        "browserProfileDir": ".spider/local/wikiwiki-browser-profile",
        "browserChannel": "chromium",
        "browserHeadless": True,
        "browserTimeoutSeconds": 75,
        "browserChallengeWaitSeconds": 20,
        "browserSettleSeconds": 2,
        "browserExecutablePath": "",
    }
    for key, default in defaults.items():
        result.setdefault(key, default)

    numeric_nonnegative = (
        "delaySeconds",
        "delayJitterSeconds",
        "rateLimitCooldownSeconds",
        "maxRateLimitRetries",
        "maxConsecutiveRateLimits",
        "transientRetrySeconds",
        "maxTransientRetries",
        "dailyLimit",
        "maxAgeDays",
        "catalogMaxAgeHours",
        "browserTimeoutSeconds",
        "browserChallengeWaitSeconds",
        "browserSettleSeconds",
    )
    for key in numeric_nonnegative:
        try:
            number = float(result[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"config.{key} must be numeric") from exc
        if number < 0:
            raise ValueError(f"config.{key} must be >= 0")
    if not isinstance(result["browserHeadless"], bool):
        raise ValueError("config.browserHeadless must be boolean")
    return result


def load_items(start2_path: Path) -> list[dict[str, Any]]:
    value = read_json(start2_path)
    if not isinstance(value, list):
        raise ValueError(f"Start2 equipment file is not a list: {start2_path}")
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        equipment_id = int(item.get("api_id") or 0)
        sort_no = int(item.get("api_sortno") or 0)
        name = str(item.get("api_name") or "").strip()
        if 0 < equipment_id < 1000 and sort_no > 0 and name:
            result.append({"equipmentId": equipment_id, "equipmentName": name})
    result.sort(key=lambda item: item["equipmentId"])
    return result


def load_catalog(catalog_path: Path) -> dict[str, Any]:
    if not catalog_path.is_file():
        raise ValueError(
            f"name catalog is missing: {catalog_path}; "
            "run `crawler.py catalog --kind equipment` first"
        )
    value = read_json(catalog_path)
    if not isinstance(value, dict) or value.get("kind") != "equipment":
        raise ValueError(f"invalid equipment name catalog: {catalog_path}")
    if not isinstance(value.get("entries"), list):
        raise ValueError(f"equipment name catalog has no entries: {catalog_path}")
    return value


NAME_MATCH_STATUSES = ("resolved", "ambiguous", "unresolved", "excluded", "invalid")


def item_url(item: dict[str, Any], catalog: dict[str, Any], aliases: dict[str, str | None]) -> dict[str, Any]:
    return resolve_name(str(item["equipmentName"]), catalog, aliases=aliases)


def _red_warning(message: str) -> str:
    prefix = "\x1b[31mWARNING\x1b[0m" if sys.stderr.isatty() else "WARNING"
    return f"{prefix}: {message}"


def _invalid_name_match(
    item: dict[str, Any],
    *,
    reason: str,
    exception: BaseException | None = None,
    resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostic = {
        "reason": reason,
        "equipmentId": int(item.get("equipmentId") or 0),
        "equipmentName": str(item.get("equipmentName") or ""),
    }
    if exception is not None:
        diagnostic.update({
            "exceptionType": type(exception).__name__,
            "exceptionMessage": str(exception),
        })
    if resolution is not None:
        diagnostic["resolutionStatus"] = str(resolution.get("status"))
        diagnostic["resolutionKeys"] = sorted(str(key) for key in resolution)
    return {
        "status": "invalid",
        "matchType": "invalid-name-match",
        "candidates": [],
        "diagnostics": [diagnostic],
    }


def _safe_item_url(item: dict[str, Any], catalog: dict[str, Any], aliases: dict[str, str | None]) -> dict[str, Any]:
    try:
        resolution = item_url(item, catalog, aliases)
    except (KeyError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        return _invalid_name_match(item, reason="resolver-exception", exception=exc)
    if not isinstance(resolution, dict):
        return _invalid_name_match(item, reason="resolver-returned-non-object")
    status = str(resolution.get("status") or "").strip()
    if status not in NAME_MATCH_STATUSES:
        return _invalid_name_match(item, reason="unknown-resolution-status", resolution=resolution)
    if status == "resolved":
        missing = [key for key in ("wikiName", "url", "urlSource") if not resolution.get(key)]
        if missing:
            invalid = _invalid_name_match(item, reason="resolved-match-missing-fields", resolution=resolution)
            invalid["diagnostics"][0]["missingFields"] = missing
            return invalid
    return resolution


def build_name_match_report(items: list[dict[str, Any]], catalog: dict[str, Any], aliases: dict[str, str | None]) -> dict[str, Any]:
    matches = []
    diagnostics: list[dict[str, Any]] = []
    counts = {status: 0 for status in NAME_MATCH_STATUSES}
    for item in items:
        resolution = _safe_item_url(item, catalog, aliases)
        status = str(resolution.get("status") or "invalid")
        counts[status] += 1
        match = {
            "equipmentId": int(item["equipmentId"]),
            "start2Name": str(item["equipmentName"]),
            "status": status,
            "matchType": resolution.get("matchType"),
        }
        if status == "resolved":
            match.update({
                "wikiName": resolution["wikiName"],
                "url": resolution["url"],
                "urlSource": resolution["urlSource"],
            })
        else:
            match["candidates"] = resolution.get("candidates", [])
            if status == "invalid":
                item_diagnostics = resolution.get("diagnostics", [])
                if isinstance(item_diagnostics, list):
                    match["diagnostics"] = item_diagnostics
                    diagnostics.extend(raw for raw in item_diagnostics if isinstance(raw, dict))
        matches.append(match)
    return {
        "schemaVersion": 1,
        "joinKey": "name",
        "counts": counts,
        "diagnostics": diagnostics,
        "matches": matches,
    }


def build_improvement_validation_catalog(raw_path: Path, *, source_url: str) -> dict[str, Any]:
    """Return a minimal validation-index catalog for the WikiWiki improvement table.

    The improvement table is not a Start2/equipment identity source.  The raw
    page is captured as cross-validation evidence and parsed later by the
    offline data pipeline.
    """

    text = raw_path.read_text("utf-8", errors="ignore")
    return {
        "schemaVersion": 1,
        "kind": "improvement",
        "role": CATALOG_ROLES["improvement"],
        "sourceUrl": source_url,
        "joinKey": "none-validation-only",
        "entries": [],
        "diagnostics": {
            "bytes": raw_path.stat().st_size,
            "anchors": text.count("<a "),
            "tables": text.lower().count("<table"),
            "validationOnly": True,
        },
    }


def _relative_project_path(path: Path, project: Path) -> str:
    try:
        return path.resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        return str(path)


def _pending_details() -> dict[str, Any]:
    return {
        "equipment": {
            "role": DETAIL_ROLES["equipment"],
            "status": "pending",
            "reason": "equipment detail crawl has not completed for this acquisition",
        },
        "ship": {
            "role": DETAIL_ROLES["ship"],
            "status": "deferred",
            "reason": "ship detail parsing is intentionally deferred; ship index locator is required",
        },
    }


def _details_from_summary(*, summary: dict[str, Any], output: Path, raw_root: Path, project: Path) -> dict[str, Any]:
    stop_reason = summary.get("stopReason") or None
    failed = int(summary.get("failed", 0) or 0)
    remaining = int(summary.get("remaining", 0) or 0)
    selected = int(summary.get("selected", 0) or 0)
    status = "ready" if selected > 0 and remaining == 0 and failed == 0 and not stop_reason else "incomplete"
    equipment = {
        "role": DETAIL_ROLES["equipment"],
        "status": status,
        "summaryPath": _relative_project_path(output / "summary.json", project),
        "recordsPath": _relative_project_path(output / "records.json", project),
        "rawRoot": _relative_project_path(raw_root, project),
        "selected": selected,
        "completed": int(summary.get("completed", 0) or 0),
        "saved": int(summary.get("saved", 0) or 0),
        "skipped": int(summary.get("skipped", 0) or 0),
        "sourceExcluded": int(summary.get("sourceExcluded", 0) or 0),
        "remaining": remaining,
        "failed": failed,
        "stopReason": stop_reason,
        "nextEquipmentId": summary.get("nextEquipmentId"),
        "updatedAt": summary.get("updatedAt"),
        "finishedAt": summary.get("finishedAt"),
    }
    if status != "ready":
        reasons = []
        if selected <= 0:
            reasons.append("selected=0")
        if remaining:
            reasons.append(f"remaining={remaining}")
        if failed:
            reasons.append(f"failed={failed}")
        if stop_reason:
            reasons.append(f"stopReason={stop_reason}")
        equipment["reason"] = "; ".join(reasons) or "unknown"
    return {
        "equipment": equipment,
        "ship": {
            "role": DETAIL_ROLES["ship"],
            "status": "deferred",
            "reason": "ship detail parsing is intentionally deferred; ship index locator is required",
        },
    }


def build_source_receipt(*, catalog_dir: Path, raw_root: Path, project: Path, details: dict[str, Any] | None = None) -> dict[str, Any]:
    indexes: dict[str, dict[str, Any]] = {}
    indexes_ready = True
    for kind, role in CATALOG_ROLES.items():
        catalog_path = catalog_dir / f"{kind}-pages.json"
        entry: dict[str, Any] = {
            "kind": kind,
            "role": role,
            "catalogPath": _relative_project_path(catalog_path, project),
            "status": "missing",
        }
        if catalog_path.is_file():
            try:
                payload = read_json(catalog_path)
                raw_cache_key = str(payload.get("rawCacheKey") or "") if isinstance(payload, dict) else ""
                raw_path = raw_root / raw_cache_key if raw_cache_key else None
                entry.update({
                    "status": "ready" if raw_path is not None and raw_path.is_file() else "raw-missing",
                    "sourceUrl": payload.get("sourceUrl") if isinstance(payload, dict) else None,
                    "rawCacheKey": raw_cache_key or None,
                    "entryCount": len(payload.get("entries", [])) if isinstance(payload, dict) and isinstance(payload.get("entries"), list) else 0,
                })
                if entry["status"] != "ready":
                    indexes_ready = False
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                entry.update({"status": "invalid", "error": f"{type(exc).__name__}: {exc}"})
                indexes_ready = False
        else:
            indexes_ready = False
        indexes[kind] = entry
    detail_payload = details or _pending_details()
    equipment_details = detail_payload.get("equipment") if isinstance(detail_payload, dict) else None
    ship_details = detail_payload.get("ship") if isinstance(detail_payload, dict) else None
    details_ready = (
        isinstance(equipment_details, dict)
        and equipment_details.get("status") == "ready"
        and isinstance(ship_details, dict)
        and ship_details.get("status") in {"deferred", "ready"}
    )
    return {
        "schemaVersion": 1,
        "source": "wikiwiki-jp",
        "mode": "source-acquisition-receipt",
        "generatedAt": utc_now(),
        "ready": bool(indexes_ready and details_ready),
        "requiredIndexes": ["ship", "equipment", "improvement"],
        "requiredDetails": {
            "equipment": "ready",
            "ship": "deferred-or-ready",
        },
        "roles": dict(CATALOG_ROLES),
        "detailRoles": dict(DETAIL_ROLES),
        "rawRoot": _relative_project_path(raw_root, project),
        "indexes": indexes,
        "details": detail_payload,
    }


def write_source_receipt(*, catalog_dir: Path, raw_root: Path, project: Path, output: Path, details: dict[str, Any] | None = None) -> dict[str, Any]:
    receipt = build_source_receipt(catalog_dir=catalog_dir, raw_root=raw_root, project=project, details=details)
    write_json_atomic(output, receipt)
    return receipt


def load_records(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    value = read_json(path)
    if not isinstance(value, dict):
        return {}
    records = value.get("records")
    return records if isinstance(records, dict) else {}


def curl_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "") + '"'


def run_curl(
    *,
    config: dict[str, Any],
    url: str,
    output_path: Path,
    state_dir: Path,
) -> tuple[int, int, str]:
    curl_path = str(config.get("curlPath") or "curl")
    resolved = shutil.which(curl_path) if os.path.sep not in curl_path else curl_path
    if not resolved or not Path(resolved).exists():
        raise RuntimeError(f"curl executable not found: {curl_path}")

    state_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=state_dir, delete=False, prefix="curl-", suffix=".conf"
    ) as handle:
        conf_path = Path(handle.name)
        os.chmod(conf_path, 0o600)
        lines = [
            "silent",
            "show-error",
            "location",
            "compressed",
            "connect-timeout = 20",
            "max-time = 75",
            "retry = 0",
            f"user-agent = {curl_quote(str(config['userAgent']))}",
            f"header = {curl_quote('accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8')}",
            f"header = {curl_quote('accept-language: ' + str(config['acceptLanguage']))}",
            f"header = {curl_quote('cache-control: no-cache')}",
        ]
        lines.extend(
            f"header = {curl_quote(str(header))}"
            for header in config.get("headers", [])
            if str(header).strip()
        )
        lines.extend([
            f"cookie = {curl_quote(str(config['cookie']))}",
            f"output = {curl_quote(str(output_path))}",
            f"write-out = {curl_quote('%{http_code}')}",
            f"url = {curl_quote(url)}",
        ])
        handle.write("\n".join(lines) + "\n")

    try:
        completed = subprocess.run(
            [str(resolved), "--config", str(conf_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        conf_path.unlink(missing_ok=True)

    raw_code = completed.stdout.strip()[-3:]
    http_code = int(raw_code) if raw_code.isdigit() else 0
    return completed.returncode, http_code, completed.stderr.strip()


def _browser_headers(config: dict[str, Any]) -> dict[str, str]:
    result = {"Accept-Language": str(config["acceptLanguage"])}
    for item in config.get("headers", []):
        name, separator, value = str(item).partition(":")
        if separator and name.strip() and value.strip():
            result[name.strip()] = value.strip()
    return result


def _playwright_context(config: dict[str, Any], project: Path, *, headless: bool | None = None):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed; install project dependencies for the current python3 and "
            "run `playwright install chromium`"
        ) from exc

    profile = Path(str(config["browserProfileDir"])).expanduser()
    if not profile.is_absolute():
        profile = (project / profile).resolve()
    profile.mkdir(parents=True, exist_ok=True)

    manager = sync_playwright().start()
    launch: dict[str, Any] = {
        "user_data_dir": str(profile),
        "headless": bool(config["browserHeadless"] if headless is None else headless),
        "user_agent": str(config["userAgent"]),
        "extra_http_headers": _browser_headers(config),
        "args": list(config.get("browserArgs", [])),
    }
    channel = str(config.get("browserChannel") or "chromium").strip()
    if channel and channel != "chromium":
        launch["channel"] = channel
    executable = str(config.get("browserExecutablePath") or "").strip()
    if executable:
        launch["executable_path"] = executable
    try:
        context = manager.chromium.launch_persistent_context(**launch)
    except Exception:
        manager.stop()
        raise
    return manager, context, profile


def run_playwright(
    *,
    config: dict[str, Any],
    url: str,
    output_path: Path,
    state_dir: Path,
    project: Path,
) -> tuple[int, int, str]:
    state_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manager = None
    context = None
    response = None
    try:
        manager, context, _profile = _playwright_context(config, project)
        page = context.pages[0] if context.pages else context.new_page()
        timeout_ms = int(float(config["browserTimeoutSeconds"]) * 1000)
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

        challenge_deadline = time.monotonic() + float(config["browserChallengeWaitSeconds"])
        content = page.content()
        while any(marker in content for marker in CHALLENGE_MARKERS) and time.monotonic() < challenge_deadline:
            page.wait_for_timeout(1000)
            content = page.content()
        settle_ms = int(float(config["browserSettleSeconds"]) * 1000)
        if settle_ms > 0:
            page.wait_for_timeout(settle_ms)
            content = page.content()
        output_path.write_text(content, encoding="utf-8")
        return 0, int(response.status if response is not None else 0), ""
    except Exception as exc:
        try:
            if context is not None and context.pages:
                output_path.write_text(context.pages[0].content(), encoding="utf-8")
        except Exception:
            pass
        return 1, int(response.status if response is not None else 0), f"{type(exc).__name__}: {exc}"
    finally:
        if context is not None:
            context.close()
        if manager is not None:
            manager.stop()


def run_request(
    *,
    config: dict[str, Any],
    url: str,
    output_path: Path,
    state_dir: Path,
    project: Path,
) -> tuple[int, int, str]:
    if config.get("transport") == "playwright":
        return run_playwright(
            config=config,
            url=url,
            output_path=output_path,
            state_dir=state_dir,
            project=project,
        )
    return run_curl(config=config, url=url, output_path=output_path, state_dir=state_dir)


def _record_timestamp(record: dict[str, Any], raw_path: Path) -> float:
    fetched = record.get("fetchedAt")
    if isinstance(fetched, str) and fetched:
        try:
            parsed = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            pass
    return raw_path.stat().st_mtime


def _cache_is_fresh(raw_root: Path, raw_path: Path, max_age_hours: float) -> bool:
    if max_age_hours <= 0:
        return False
    entry = read_meta_index(raw_root).get(raw_path.resolve().relative_to(raw_root.resolve()).as_posix(), {})
    timestamp = entry.get("validated_at") or entry.get("fetched_at")
    try:
        fetched_at = float(timestamp)
    except (TypeError, ValueError):
        fetched_at = raw_path.stat().st_mtime
    return time.time() - fetched_at <= max_age_hours * 3600


def session_command(args: argparse.Namespace) -> int:
    project = args.project.resolve()
    config_path = (project / args.config).resolve() if not args.config.is_absolute() else args.config
    config = load_browser_session_config(config_path)
    if config.get("transport") != "playwright":
        raise OperatorStop(
            "wikiwiki-browser-transport-required",
            "会话引导只适用于 Playwright 浏览器传输。",
            "将 config.transport 改为 playwright 后重试。",
            str(config_path),
        )

    manager = None
    context = None
    try:
        manager, context, profile = _playwright_context(config, project, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(args.url, wait_until="domcontentloaded", timeout=int(args.timeout_seconds * 1000))
        deadline = time.monotonic() + args.timeout_seconds
        print(f"浏览器会话已打开：{args.url}")
        print("如出现 Cloudflare 交互验证，请在该浏览器窗口中完成；脚本会自动检测通过状态。")
        while time.monotonic() < deadline:
            content = page.content()
            if not any(marker in content for marker in CHALLENGE_MARKERS):
                print(f"WikiWiki 浏览器会话已就绪；持久 Profile：{profile}")
                return 0
            page.wait_for_timeout(1000)
        raise OperatorStop(
            "cloudflare-interactive-challenge-timeout",
            "Cloudflare 交互验证在限定时间内未完成。",
            "在同一 Runner 主机上重新执行 session，并在浏览器窗口完成验证。",
            str(profile),
        )
    finally:
        if context is not None:
            context.close()
        if manager is not None:
            manager.stop()


def page_id(path: Path) -> int | None:
    try:
        text = path.read_text("utf-8", errors="ignore")
    except OSError:
        return None
    match = PAGE_ID_RE.search(text)
    return int(match.group(1)) if match else None


def is_challenge(path: Path) -> bool:
    try:
        text = path.read_text("utf-8", errors="ignore")[:500_000]
    except OSError:
        return False
    return any(marker in text for marker in CHALLENGE_MARKERS)


def is_resumable_record(
    record: dict[str, Any],
    raw_path: Path,
    *,
    max_age_days: float | None = None,
) -> bool:
    if record.get("status") not in {"saved", "saved-id-mismatch", "saved-id-missing"}:
        return False
    if not raw_path.is_file() or raw_path.stat().st_size < 256:
        return False
    expected = record.get("sha256")
    if expected and expected != sha256_file(raw_path):
        return False
    if max_age_days is not None:
        if max_age_days <= 0:
            return False
        if time.time() - _record_timestamp(record, raw_path) > max_age_days * 86400:
            return False
    return True


def sleep_delay(config: dict[str, Any]) -> None:
    delay = float(config["delaySeconds"])
    jitter = float(config["delayJitterSeconds"])
    actual = max(0.0, delay + random.uniform(-jitter, jitter))
    if actual > 0:
        time.sleep(actual)


def save_state(
    *,
    records_path: Path,
    summary_path: Path,
    records: dict[str, dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    write_json_atomic(records_path, {"schemaVersion": 1, "records": records})
    write_json_atomic(summary_path, summary)


def select_items(
    items: list[dict[str, Any]],
    *,
    equipment_ids: list[int] | None,
    from_id: int | None,
) -> list[dict[str, Any]]:
    if equipment_ids:
        selected_ids = set(equipment_ids)
        items = [item for item in items if item["equipmentId"] in selected_ids]
    if from_id is not None:
        items = [item for item in items if item["equipmentId"] >= from_id]
    return items


def fetch_catalog_page(
    *,
    config: dict[str, Any],
    url: str,
    raw_root: Path,
    state_dir: Path,
    project: Path,
    refresh: bool,
    offline: bool,
    kind: str,
) -> tuple[Path, str]:
    raw_path = url_to_cache_path(raw_root, url)
    if not refresh and raw_path.is_file() and raw_path.stat().st_size >= 256:
        if offline or _cache_is_fresh(raw_root, raw_path, float(config["catalogMaxAgeHours"])):
            return raw_path, "raw-cache"
    if offline:
        raise OperatorStop(
            "wikiwiki-catalog-cache-missing",
            f"离线模式缺少 WikiWiki {kind} 目录缓存：{raw_path}",
            "先在有效浏览器会话下执行 catalog 抓取，或恢复对应原始缓存。",
            str(raw_path),
        )

    rate_retries = 0
    while True:
        temp_path = state_dir / f"catalog-{kind}.download"
        temp_path.unlink(missing_ok=True)
        exit_code, http_code, stderr = run_request(
            config=config,
            url=url,
            output_path=temp_path,
            state_dir=state_dir,
            project=project,
        )
        if http_code == 429:
            rate_retries += 1
            max_retries = int(float(config["maxRateLimitRetries"]))
            if rate_retries > max_retries:
                temp_path.unlink(missing_ok=True)
                raise OperatorStop(
                    "wikiwiki-rate-limit-persistent",
                    f"WikiWiki {kind} 目录持续返回 HTTP 429。",
                    "暂停抓取并等待站点限流窗口恢复；保留现有目录缓存后再重试。",
                    str(raw_path),
                    details={"kind": kind, "url": url, "retryCount": rate_retries},
                )
            cooldown = float(config["rateLimitCooldownSeconds"]) * (2 ** (rate_retries - 1))
            print(f"[catalog:{kind}] HTTP 429; site cooldown {cooldown:.0f}s")
            temp_path.unlink(missing_ok=True)
            time.sleep(cooldown)
            continue
        if exit_code != 0:
            temp_path.unlink(missing_ok=True)
            raise OperatorStop(
                "wikiwiki-network-retry-exhausted",
                f"WikiWiki {kind} 目录网络请求失败：{stderr or exit_code}",
                "检查网络、代理和 curl 配置；修复后可继续使用现有缓存。",
                str(raw_path),
                details={"kind": kind, "url": url, "curlExitCode": exit_code},
            )
        if temp_path.is_file() and is_challenge(temp_path):
            temp_path.unlink(missing_ok=True)
            raise OperatorStop(
                "cloudflare-session-invalid",
                f"WikiWiki {kind} 目录返回 Cloudflare 挑战页。",
                "在浏览器重新通过 Cloudflare 验证并导出新的 Cookie/请求头。",
                str(raw_path),
                details={"kind": kind, "url": url},
            )
        if http_code != 200:
            temp_path.unlink(missing_ok=True)
            raise OperatorStop(
                "wikiwiki-catalog-http-error",
                f"WikiWiki {kind} 目录返回 HTTP {http_code}。",
                "检查页面地址、Cookie 和站点状态后重试。",
                str(raw_path),
                details={"kind": kind, "url": url, "httpCode": http_code},
            )
        if not temp_path.is_file() or temp_path.stat().st_size < 256:
            temp_path.unlink(missing_ok=True)
            raise OperatorStop(
                "wikiwiki-empty-response",
                f"WikiWiki {kind} 目录响应为空。",
                "检查浏览器会话、代理与页面地址后重试。",
                str(raw_path),
                details={"kind": kind, "url": url},
            )
        captured_at = utc_now()
        raw_path, _, _ = install_capture(
            temp_path,
            raw_root=raw_root,
            url=url,
            fetched_at=captured_at,
            http_code=http_code,
            overwrite=True,
            remove_source=True,
            capture_metadata={"catalogKind": kind, "urlSource": "wikiwiki-card-list"},
        )
        return raw_path, "network"


def catalog_command(args: argparse.Namespace) -> int:
    project = args.project.resolve()
    config_path = (project / args.config).resolve() if not args.config.is_absolute() else args.config
    start2_path = (project / args.start2).resolve() if not args.start2.is_absolute() else args.start2
    alias_path = (project / args.name_aliases).resolve() if not args.name_aliases.is_absolute() else args.name_aliases
    aliases = load_name_aliases(alias_path)
    output = (project / args.output).resolve() if not args.output.is_absolute() else args.output
    raw_root = (project / args.raw_root).resolve() if not args.raw_root.is_absolute() else args.raw_root
    catalog_dir = (project / args.catalog_dir).resolve() if not args.catalog_dir.is_absolute() else args.catalog_dir
    config = load_browser_session_config(config_path)
    kinds = list(CATALOG_SOURCES) if args.kind == "all" else [args.kind]
    state_dir = output / "state"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)

    for kind in kinds:
        source_url = CATALOG_SOURCES[kind]
        try:
            raw_path, capture_source = fetch_catalog_page(
                config=config,
                url=source_url,
                raw_root=raw_root,
                state_dir=state_dir,
                project=project,
                refresh=args.refresh,
                offline=args.offline,
                kind=kind,
            )
            if kind in {"equipment", "ship"}:
                catalog = parse_card_catalog(
                    raw_path.read_text("utf-8", errors="ignore"),
                    kind=kind,
                    source_url=source_url,
                )
            else:
                catalog = build_improvement_validation_catalog(raw_path, source_url=source_url)
            catalog.update({
                "generatedAt": utc_now(),
                "rawPath": str(raw_path.relative_to(project)) if project in raw_path.parents else str(raw_path),
                "rawCacheKey": raw_path.relative_to(raw_root).as_posix(),
                "captureSource": capture_source,
                "role": CATALOG_ROLES[kind],
            })
            target = catalog_dir / f"{kind}-pages.json"
            write_json_atomic(target, catalog)
            match_report = None
            if kind == "equipment":
                match_report = build_name_match_report(load_items(start2_path), catalog, aliases)
                match_report.update({"generatedAt": utc_now(), "catalogPath": str(target)})
                write_json_atomic(catalog_dir / "equipment-name-matches.json", match_report)
            diagnostics = catalog["diagnostics"]
            if kind in {"equipment", "ship"}:
                print(
                    f"[catalog:{kind}] role={CATALOG_ROLES[kind]} "
                    f"entries={diagnostics['entries']} "
                    f"ambiguous={len(diagnostics['ambiguousNormalizedNames'])} "
                    f"fallbackUrls={diagnostics['displayNameUrlFallbacks']} "
                    f"source={capture_source}"
                )
            else:
                print(
                    f"[catalog:{kind}] role={CATALOG_ROLES[kind]} "
                    f"bytes={diagnostics['bytes']} tables={diagnostics['tables']} "
                    f"source={capture_source}"
                )
            print(f"[catalog:{kind}] output={target}")
            if match_report is not None:
                counts = match_report["counts"]
                print(
                    f"[catalog:{kind}] nameMatches resolved={counts['resolved']} "
                    f"ambiguous={counts['ambiguous']} unresolved={counts['unresolved']} "
                    f"excluded={counts['excluded']} invalid={counts['invalid']}"
                )
                if counts.get("invalid", 0):
                    print(_red_warning(
                        f"WikiWiki {kind} name-match report contains "
                        f"{counts['invalid']} invalid resolver results; "
                        f"see {catalog_dir / 'equipment-name-matches.json'}"
                    ), file=sys.stderr)
        except OperatorStop:
            raise
        except (OSError, ValueError, RuntimeError, LookupError, TypeError, json.JSONDecodeError) as exc:
            raise OperatorStop(
                "wikiwiki-catalog-invalid",
                f"WikiWiki {kind} 目录无法生成：{type(exc).__name__}: {exc}",
                "检查目录原始页面、名称别名和解析规则后重试。",
                str(catalog_dir),
                details={"kind": kind, "sourceUrl": source_url},
            ) from exc
    receipt = write_source_receipt(
        catalog_dir=catalog_dir,
        raw_root=raw_root,
        project=project,
        output=output / "source-receipt.json",
    )
    print(
        "[source-receipt] "
        f"ready={str(bool(receipt['ready'])).lower()} "
        f"output={output / 'source-receipt.json'}"
    )
    indexes_ready = all(
        isinstance(receipt.get("indexes", {}).get(kind), dict)
        and receipt["indexes"][kind].get("status") == "ready"
        for kind in ("ship", "equipment", "improvement")
    )
    if args.kind == "all" and not indexes_ready:
        raise OperatorStop(
            "wikiwiki-source-indexes-incomplete",
            "WikiWiki 三索引 source acquisition indexes 未就绪。",
            "重新执行 catalog 抓取，确保 ship/equipment/improvement 三个索引均有原始缓存。",
            str(output / "source-receipt.json"),
            details={"indexes": receipt["indexes"]},
        )
    return 0


def inspect_command(args: argparse.Namespace) -> int:
    project = args.project.resolve()
    config_path = (project / args.config).resolve() if not args.config.is_absolute() else args.config
    start2_path = (project / args.start2).resolve() if not args.start2.is_absolute() else args.start2
    alias_path = (project / args.name_aliases).resolve() if not args.name_aliases.is_absolute() else args.name_aliases
    aliases = load_name_aliases(alias_path)
    catalog_path = (project / args.catalog).resolve() if not args.catalog.is_absolute() else args.catalog
    config = load_browser_session_config(config_path)
    items = load_items(start2_path)
    print("WikiWiki external crawler ready")
    print(f"- project: {project}")
    print(f"- equipment: {len(items)}")
    print(f"- transport: {config['transport']}")
    if config["transport"] == "curl":
        print(f"- curl: {config['curlPath']}")
    else:
        print(f"- browser profile: {config['browserProfileDir']}")
        print(f"- browser channel: {config['browserChannel']}")
    print(f"- delay: {float(config['delaySeconds']):.1f}s ± {float(config['delayJitterSeconds']):.1f}s")
    print(f"- rate-limit cooldown: {int(float(config['rateLimitCooldownSeconds']))}s")
    if config["transport"] == "curl":
        print("- cookie: configured (redacted)")
    else:
        print("- session: persistent browser profile")
    if catalog_path.is_file():
        catalog = load_catalog(catalog_path)
        counts = build_name_match_report(items, catalog, aliases)["counts"]
        print(f"- name catalog: {catalog_path}")
        print(
            f"- name matches: resolved={counts['resolved']}, "
            f"ambiguous={counts['ambiguous']}, unresolved={counts['unresolved']}, "
            f"excluded={counts['excluded']}, invalid={counts['invalid']}"
        )
        if counts.get("invalid", 0):
            print(_red_warning(
                "WikiWiki equipment name catalog contains invalid resolver results; "
                "run catalog and inspect .spider/local/wikiwiki-crawler/catalog/equipment-name-matches.json"
            ), file=sys.stderr)
    else:
        print(f"- name catalog: missing ({catalog_path})")
        print("- next: crawler.py catalog --kind equipment")
    return 0

def crawl_command(args: argparse.Namespace) -> int:
    project = args.project.resolve()
    config_path = (project / args.config).resolve() if not args.config.is_absolute() else args.config
    output = (project / args.output).resolve() if not args.output.is_absolute() else args.output
    raw_root = (project / args.raw_root).resolve() if not args.raw_root.is_absolute() else args.raw_root
    start2_path = (project / args.start2).resolve() if not args.start2.is_absolute() else args.start2
    alias_path = (project / args.name_aliases).resolve() if not args.name_aliases.is_absolute() else args.name_aliases
    catalog_path = (project / args.catalog).resolve() if not args.catalog.is_absolute() else args.catalog

    try:
        config = load_browser_session_config(config_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise OperatorStop(
            "wikiwiki-session-config-invalid",
            f"WikiWiki Cookie/浏览器会话配置不可用：{exc}",
            "从当前浏览器重新导出可用 Cookie 和请求头，更新 configs/wikiwiki-crawler.local.json。",
            str(config_path),
        ) from exc
    aliases = load_name_aliases(alias_path)
    items = select_items(
        load_items(start2_path),
        equipment_ids=args.equipment_ids,
        from_id=args.from_id,
    )
    catalog = load_catalog(catalog_path)
    daily_limit_value = args.limit if args.limit is not None else args.daily_limit
    if daily_limit_value is None:
        daily_limit_value = config.get("dailyLimit", 40)
    daily_limit = max(int(daily_limit_value), 0)

    state_dir = output / "state"
    records_path = output / "records.json"
    events_path = output / "events.jsonl"
    summary_path = output / "summary.json"
    operator_stop_path = output / "operator-stop.json"
    records = load_records(records_path)
    output.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "schemaVersion": 2,
        "source": "wikiwiki-jp",
        "mode": "external-browser-session-crawl",
        "startedAt": utc_now(),
        "updatedAt": utc_now(),
        "selected": len(items),
        "dailyLimit": daily_limit,
        "cycleDays": (len(items) + daily_limit - 1) // daily_limit if daily_limit else None,
        "maxAgeDays": float(config["maxAgeDays"]),
        "transport": config["transport"],
        "attempted": 0,
        "completed": 0,
        "saved": 0,
        "skipped": 0,
        "failed": 0,
        "rateLimited": 0,
        "newPages": 0,
        "changedPages": 0,
        "unchangedPages": 0,
        "idMismatch": 0,
        "idMissing": 0,
        "pageNumberMismatch": 0,
        "pageNumberMissing": 0,
        "urlResolved": 0,
        "urlAmbiguous": 0,
        "urlUnresolved": 0,
        "sourceExcluded": 0,
        "quotaReached": False,
        "stopReason": None,
        "canonicalDataChanged": False,
        "rawRoot": str(raw_root.relative_to(project)) if project in raw_root.parents else str(raw_root),
    }
    consecutive_429 = 0
    total = len(items)

    for index, item in enumerate(items, 1):
        equipment_id = int(item["equipmentId"])
        equipment_name = str(item["equipmentName"])
        key = str(equipment_id)
        resolution = item_url(item, catalog, aliases)
        previous = records.get(key, {})
        if resolution["status"] == "excluded":
            record = {
                "equipmentId": equipment_id,
                "equipmentName": equipment_name,
                "status": "source-excluded",
                "httpCode": 0,
                "fetchedAt": utc_now(),
                "matchType": resolution.get("matchType"),
            }
            records[key] = record
            summary["completed"] += 1
            summary["skipped"] += 1
            summary["sourceExcluded"] += 1
            summary["updatedAt"] = utc_now()
            append_json_line(events_path, {"at": utc_now(), "event": "source-excluded", **record})
            save_state(records_path=records_path, summary_path=summary_path, records=records, summary=summary)
            print(f"[{index}/{total}] id={equipment_id} name={equipment_name} status=source-excluded")
            continue

        if resolution["status"] != "resolved":
            final_status = f"url-{resolution['status']}"
            record = {
                "equipmentId": equipment_id,
                "equipmentName": equipment_name,
                "status": final_status,
                "httpCode": 0,
                "fetchedAt": utc_now(),
                "matchType": resolution.get("matchType"),
                "candidates": resolution.get("candidates", []),
            }
            records[key] = record
            summary["failed"] += 1
            summary["urlAmbiguous" if resolution["status"] == "ambiguous" else "urlUnresolved"] += 1
            error = OperatorStop(
                f"equipment-name-mapping-{resolution['status']}",
                f"装备页面名称映射{resolution['status']}：{equipment_id} {equipment_name}",
                "修正 configs/wikiwiki-page-name-aliases.json 或重新生成装备卡片目录后重试。",
                str(records_path),
                details={"equipmentId": equipment_id, "candidates": resolution.get("candidates", [])},
            )
            apply_operator_stop(summary, error)
            append_json_line(events_path, {"at": utc_now(), "event": "operator-stop", **error.payload()})
            save_state(records_path=records_path, summary_path=summary_path, records=records, summary=summary)
            break

        url = str(resolution["url"])
        url_source = f"name-catalog:{resolution['matchType']}"
        wiki_name = str(resolution["wikiName"])
        raw_path = url_to_cache_path(raw_root, url)
        summary["urlResolved"] += 1
        if not args.refresh and is_resumable_record(
            previous, raw_path, max_age_days=float(config["maxAgeDays"])
        ):
            summary["completed"] += 1
            summary["skipped"] += 1
            print(f"[{index}/{total}] id={equipment_id} name={equipment_name} status=resume-skip")
            continue
        if summary["attempted"] >= daily_limit:
            summary["quotaReached"] = True
            break

        previous_sha = sha256_file(raw_path) if raw_path.is_file() else None
        summary["attempted"] += 1
        rate_retries = 0
        transient_retries = 0
        final_status = "failed"
        final_http = 0
        final_error = ""
        captured_at: str | None = None
        observed_id: int | None = None
        incoming_sha: str | None = None

        while True:
            temp_path = state_dir / f"{equipment_id}.download"
            temp_path.unlink(missing_ok=True)
            exit_code, http_code, stderr = run_request(
                config=config,
                url=url,
                output_path=temp_path,
                state_dir=state_dir,
                project=project,
            )
            final_http = http_code
            final_error = stderr
            if http_code == 429:
                temp_path.unlink(missing_ok=True)
                summary["rateLimited"] += 1
                consecutive_429 += 1
                rate_retries += 1
                max_consecutive = int(float(config["maxConsecutiveRateLimits"]))
                max_retries = int(float(config["maxRateLimitRetries"]))
                if consecutive_429 >= max_consecutive or rate_retries > max_retries:
                    final_status = "deferred-rate-limit"
                    apply_operator_stop(summary, OperatorStop(
                        "repeated-http-429",
                        f"WikiWiki 持续限流，当前装备 {equipment_id} 未完成。",
                        "更换代理出口或等待限流窗口恢复；保留现有 Cookie 后从当前断点重试。",
                        str(records_path),
                        details={"equipmentId": equipment_id, "url": url},
                    ))
                    break
                cooldown = float(config["rateLimitCooldownSeconds"]) * (2 ** (rate_retries - 1))
                print(f"[{index}/{total}] id={equipment_id} HTTP 429; site cooldown {cooldown:.0f}s")
                time.sleep(cooldown)
                continue

            if exit_code != 0 or http_code in {0, 408, 425, 500, 502, 503, 504}:
                if temp_path.is_file() and is_challenge(temp_path):
                    final_status = "cloudflare-session-invalid"
                    temp_path.unlink(missing_ok=True)
                    apply_operator_stop(summary, OperatorStop(
                        "cloudflare-session-invalid",
                        "Cloudflare 会话已经失效。",
                        "在浏览器重新通过 Cloudflare 验证并导出新的 Cookie/请求头。",
                        str(records_path),
                        details={"equipmentId": equipment_id, "url": url},
                    ))
                    break
                transient_retries += 1
                if transient_retries > int(float(config["maxTransientRetries"])):
                    final_status = "transport-failed"
                    temp_path.unlink(missing_ok=True)
                    apply_operator_stop(summary, OperatorStop(
                        "network-retries-exhausted",
                        f"网络重试耗尽，当前装备 {equipment_id} 未完成。",
                        "检查网络、代理与 curl 配置后从现有 records.json 断点继续。",
                        str(records_path),
                        details={"equipmentId": equipment_id, "httpCode": http_code, "error": stderr[-500:]},
                    ))
                    break
                cooldown = float(config["transientRetrySeconds"]) * transient_retries
                temp_path.unlink(missing_ok=True)
                time.sleep(cooldown)
                continue

            if temp_path.is_file() and is_challenge(temp_path):
                final_status = "cloudflare-session-invalid"
                temp_path.unlink(missing_ok=True)
                apply_operator_stop(summary, OperatorStop(
                    "cloudflare-session-invalid",
                    "Cloudflare 返回了挑战页，当前 Cookie 不可继续使用。",
                    "在浏览器重新通过 Cloudflare 验证并导出新的 Cookie/请求头。",
                    str(records_path),
                    details={"equipmentId": equipment_id, "url": url},
                ))
                break
            if http_code != 200:
                final_status = f"http-{http_code}"
                temp_path.unlink(missing_ok=True)
                apply_operator_stop(summary, OperatorStop(
                    "wikiwiki-page-http-error",
                    f"装备页面返回 HTTP {http_code}：{equipment_id} {equipment_name}",
                    "检查页面目录映射、Cookie 和站点状态后从断点重试。",
                    str(records_path),
                    details={"equipmentId": equipment_id, "url": url, "httpCode": http_code},
                ))
                break
            if not temp_path.is_file() or temp_path.stat().st_size < 256:
                final_status = "empty-response"
                temp_path.unlink(missing_ok=True)
                apply_operator_stop(summary, OperatorStop(
                    "wikiwiki-empty-response",
                    f"装备页面响应为空：{equipment_id} {equipment_name}",
                    "检查浏览器会话与页面 URL 后从断点重试。",
                    str(records_path),
                ))
                break

            observed_id = page_id(temp_path)
            incoming_sha = sha256_file(temp_path)
            captured_at = utc_now()
            raw_path, _, incoming_sha = install_capture(
                temp_path, raw_root=raw_root, url=url, fetched_at=captured_at,
                http_code=http_code, overwrite=True, remove_source=True,
                capture_metadata={
                    "equipmentId": equipment_id,
                    "equipmentName": equipment_name,
                    "urlSource": url_source,
                    "wikiName": wiki_name,
                    "nameMatchType": resolution["matchType"],
                    "sourcePageNumber": observed_id,
                },
            )
            final_status = "saved"
            if observed_id is None:
                summary["idMissing"] += 1
                summary["pageNumberMissing"] += 1
                append_json_line(events_path, {
                    "at": utc_now(),
                    "event": "source-page-number-missing",
                    "equipmentId": equipment_id,
                    "equipmentName": equipment_name,
                    "url": url,
                })
            elif observed_id != equipment_id:
                summary["idMismatch"] += 1
                summary["pageNumberMismatch"] += 1
                append_json_line(events_path, {
                    "at": utc_now(),
                    "event": "source-page-number-mismatch",
                    "equipmentId": equipment_id,
                    "equipmentName": equipment_name,
                    "sourcePageNumber": observed_id,
                    "url": url,
                })
            consecutive_429 = 0
            break

        record = {
            "equipmentId": equipment_id, "equipmentName": equipment_name,
            "url": url, "urlSource": url_source, "wikiName": wiki_name,
            "nameMatchType": resolution["matchType"], "status": final_status,
            "httpCode": final_http, "fetchedAt": captured_at or utc_now(),
        }
        if raw_path.is_file() and final_status.startswith("saved"):
            final_sha = incoming_sha or sha256_file(raw_path)
            record.update({
                "rawPath": str(raw_path.relative_to(project)) if project in raw_path.parents else str(raw_path),
                "rawCacheKey": raw_path.relative_to(raw_root).as_posix(),
                "bytes": raw_path.stat().st_size, "sha256": final_sha,
                "sourcePageNumber": observed_id,
            })
            summary["saved"] += 1
            if previous_sha is None:
                summary["newPages"] += 1
            elif previous_sha == final_sha:
                summary["unchangedPages"] += 1
            else:
                summary["changedPages"] += 1
                summary["canonicalDataChanged"] = True
        else:
            summary["failed"] += 1
            if final_error:
                record["error"] = final_error[-1000:]
        records[key] = record
        summary["completed"] += 1
        summary["updatedAt"] = utc_now()
        append_json_line(events_path, {"at": utc_now(), "event": "item-finished", **record})
        save_state(records_path=records_path, summary_path=summary_path, records=records, summary=summary)
        print(f"[{index}/{total}] id={equipment_id} name={equipment_name} status={final_status} http={final_http}")
        if summary.get("stopReason"):
            break
        sleep_delay(config)

    remaining_ids: list[int] = []
    for item in items:
        equipment_id = int(item["equipmentId"])
        resolution = item_url(item, catalog, aliases)
        if resolution.get("status") == "excluded":
            continue
        if resolution.get("status") != "resolved":
            remaining_ids.append(equipment_id)
            continue
        candidate_path = url_to_cache_path(raw_root, str(resolution["url"]))
        if args.refresh or not is_resumable_record(
            records.get(str(equipment_id), {}),
            candidate_path,
            max_age_days=float(config["maxAgeDays"]),
        ):
            remaining_ids.append(equipment_id)
    summary.update({
        "updatedAt": utc_now(),
        "finishedAt": utc_now(),
        "remaining": len(remaining_ids),
        "nextEquipmentId": remaining_ids[0] if remaining_ids else None,
    })
    save_state(records_path=records_path, summary_path=summary_path, records=records, summary=summary)
    detail_receipt = write_source_receipt(
        catalog_dir=catalog_path.parent,
        raw_root=raw_root,
        project=project,
        output=output / "source-receipt.json",
        details=_details_from_summary(summary=summary, output=output, raw_root=raw_root, project=project),
    )
    print(
        "[source-receipt] "
        f"ready={str(bool(detail_receipt['ready'])).lower()} "
        f"equipmentDetails={detail_receipt['details']['equipment']['status']} "
        f"output={output / 'source-receipt.json'}"
    )
    if summary.get("operatorStop"):
        write_json_atomic(operator_stop_path, summary["operatorStop"])
    else:
        operator_stop_path.unlink(missing_ok=True)
    print("WikiWiki external crawl summary")
    for key in (
        "selected", "dailyLimit", "cycleDays", "attempted", "completed", "saved",
        "skipped", "newPages", "changedPages", "unchangedPages", "failed",
        "rateLimited", "remaining", "nextEquipmentId", "sourceExcluded",
        "pageNumberMismatch", "pageNumberMissing", "idMismatch", "idMissing",
    ):
        print(f"- {key}: {summary.get(key)}")
    print(f"- stopReason: {summary.get('stopReason') or 'none'}")
    print(f"- state output: {output}")
    print(f"- raw cache: {raw_root}")
    return 75 if summary.get("stopReason") else (1 if summary["failed"] else 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual WikiWiki browser-session crawler")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
        command.add_argument("--start2", type=Path, default=DEFAULT_START2)
        command.add_argument("--name-aliases", type=Path, default=DEFAULT_NAME_ALIASES)

    session_parser = subparsers.add_parser(
        "session", help="open a headed persistent browser and complete Cloudflare verification"
    )
    common(session_parser)
    session_parser.add_argument("--url", default=SOURCE_BASE)
    session_parser.add_argument("--timeout-seconds", type=int, default=600)
    session_parser.set_defaults(handler=session_command)

    inspect_parser = subparsers.add_parser("inspect", help="validate local config and name catalog")
    common(inspect_parser)
    inspect_parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    inspect_parser.set_defaults(handler=inspect_command)

    catalog_parser = subparsers.add_parser("catalog", help="capture card lists and build name-to-URL catalogs")
    common(catalog_parser)
    catalog_parser.add_argument("--kind", choices=("equipment", "ship", "improvement", "all"), default="all")
    catalog_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    catalog_parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    catalog_parser.add_argument("--catalog-dir", type=Path, default=DEFAULT_CATALOG_DIR)
    catalog_parser.add_argument("--refresh", action="store_true")
    catalog_parser.add_argument("--offline", action="store_true")
    catalog_parser.set_defaults(handler=catalog_command)

    crawl_parser = subparsers.add_parser("crawl", help="capture or resume raw equipment pages")
    common(crawl_parser)
    crawl_parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    crawl_parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help="crawler state/log directory (HTML is written to --raw-root)",
    )
    crawl_parser.add_argument(
        "--raw-root", type=Path, default=DEFAULT_RAW_ROOT,
        help="shared raw HTTP cache root consumed by the offline parser",
    )
    crawl_parser.add_argument("--equipment-id", type=int, action="append", dest="equipment_ids")
    crawl_parser.add_argument("--from-id", type=int)
    crawl_parser.add_argument(
        "--daily-limit", type=int, default=None,
        help="temporary override for config.dailyLimit; resume skips do not count",
    )
    crawl_parser.add_argument(
        "--limit", type=int,
        help="compatibility override for --daily-limit",
    )
    crawl_parser.add_argument("--refresh", action="store_true")
    crawl_parser.set_defaults(handler=crawl_command)
    return parser


def persist_operator_stop(args: argparse.Namespace, error: OperatorStop) -> None:
    output_value = getattr(args, "output", DEFAULT_OUTPUT)
    output = output_value if isinstance(output_value, Path) else Path(str(output_value))
    project = getattr(args, "project", Path.cwd()).resolve()
    output = output.resolve() if output.is_absolute() else (project / output).resolve()
    write_json_atomic(output / "operator-stop.json", error.payload())


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except OperatorStop as exc:
        persist_operator_stop(args, exc)
        print_operator_stop(exc)
        return exc.exit_code
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        error = OperatorStop(
            "crawler-unhandled-error",
            f"WikiWiki crawler 无法继续：{type(exc).__name__}: {exc}",
            "检查输入文件、配置与最近日志；修复后可继续使用现有断点。",
            str(getattr(args, "output", DEFAULT_OUTPUT)),
            exit_code=2,
        )
        persist_operator_stop(args, error)
        print_operator_stop(error)
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
