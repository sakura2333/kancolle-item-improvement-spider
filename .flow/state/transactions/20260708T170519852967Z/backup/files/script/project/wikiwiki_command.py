#!/usr/bin/env python3
from __future__ import annotations

"""Formal Flow entry for the WikiWiki browser-session acquisition source.

This module is intentionally a thin wrapper.  It does not parse WikiWiki HTML,
read crawler records, touch snapshots, or build the data package.  It only
invokes the browser-session acquisition tool through a subprocess so that
`./flow run` can continue to consume and validate the resulting raw evidence
through the existing offline data pipeline.
"""

from datetime import datetime, timezone
import json
from pathlib import Path

from script.project.command_support import result, run_logged

LOCAL_CONFIG_PATH = Path("configs") / "wikiwiki-crawler.local.json"
DEFAULT_CONFIG_PATH = Path("configs") / "wikiwiki-crawler.default.json"
LEGACY_LOCAL_CONFIG_PATH = Path(".flow") / "local" / "wikiwiki-curl.json"
TOOL_DIR = Path("tools") / "wikiwiki-crawler"
CRAWLER_SCRIPT = TOOL_DIR / "crawler.py"
FULL_REFRESH_LIMIT = 10000


def _write_preflight_log(root: Path, label: str, title: str, lines: list[str]) -> Path:
    logs = root / ".flow" / "state" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = logs / f"{stamp}-{label}.log"
    body = [title, "", *lines, ""]
    path.write_text("\n".join(body), encoding="utf-8")
    return path


def _usage_error(message: str) -> dict:
    return result(
        "失败",
        message,
        [],
        [message],
        "执行 ./flow wikiwiki、./flow wikiwiki --full、./flow wikiwiki smoke、./flow wikiwiki config 或 ./flow wikiwiki session",
        "无需回滚",
        2,
    )


def _source_config_template(root: Path) -> tuple[Path, str]:
    default = root / DEFAULT_CONFIG_PATH
    if default.is_file():
        return default, "default"
    raise RuntimeError(f"缺少 WikiWiki 默认配置：{DEFAULT_CONFIG_PATH.as_posix()}")


def _materialize_local_config(root: Path) -> tuple[bool, Path, Path, str, bool]:
    """Create the Spring-style local WikiWiki config under ``configs``.

    ``configs/wikiwiki-crawler.default.json`` is committed and readable.
    ``configs/wikiwiki-crawler.local.json`` is ignored and user-editable.
    Legacy ``.flow/local/wikiwiki-curl.json`` is copied forward once so existing
    browser-session settings are not lost.  ``.flow/local`` remains runtime
    state only: cache, source receipt, and browser profile.
    """
    path = root / LOCAL_CONFIG_PATH
    if path.is_file():
        source = root / DEFAULT_CONFIG_PATH
        source_kind = "default" if source.is_file() else "local-only"
        return False, path, source, source_kind, False
    source, source_kind = _source_config_template(root)
    legacy = root / LEGACY_LOCAL_CONFIG_PATH
    if legacy.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        return True, path, legacy, "legacy-local", True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return True, path, source, source_kind, False


def _ensure_config(root: Path) -> dict | None:
    try:
        created, path, source, source_kind, migrated = _materialize_local_config(root)
    except RuntimeError as exc:
        log_path = _write_preflight_log(
            root,
            "wikiwiki-config",
            "WikiWiki config bootstrap failed",
            [str(exc)],
        )
        return result(
            "失败",
            "缺少 WikiWiki 默认配置",
            [f"诊断日志：{log_path.relative_to(root)}"],
            [str(exc)],
            f"恢复 {DEFAULT_CONFIG_PATH.as_posix()} 后重新执行 ./flow wikiwiki config",
            "无需回滚",
            2,
        )
    if not created:
        return None
    details = [
        f"source: {source.relative_to(root) if source.is_relative_to(root) else source}",
        f"sourceKind: {source_kind}",
        f"local: {LOCAL_CONFIG_PATH.as_posix()}",
        "local config is ignored by Git and is the only user-editable WikiWiki config entry",
        "runtime cache/receipt/browser profile remain under .flow/local",
        "review browserHeadless/browserProfileDir/cookie/headers before the first full acquisition",
    ]
    if migrated:
        details.append(f"migrated legacy local config from {LEGACY_LOCAL_CONFIG_PATH.as_posix()}")
    log_path = _write_preflight_log(
        root,
        "wikiwiki-config",
        "WikiWiki local config materialized",
        details,
    )
    completed = [
        f"本地配置：{path.relative_to(root)}",
        f"默认配置：{DEFAULT_CONFIG_PATH.as_posix()}",
        f"诊断日志：{log_path.relative_to(root)}",
    ]
    if migrated:
        completed.append(f"已从旧路径迁移：{LEGACY_LOCAL_CONFIG_PATH.as_posix()}")
    return result(
        "失败",
        "已生成 WikiWiki 本地配置，需确认后重跑",
        completed,
        ["尚未执行 WikiWiki source acquisition"],
        f"检查并按本机调整 {LOCAL_CONFIG_PATH.as_posix()}，然后重新执行 ./flow wikiwiki --full",
        "无需回滚；本地配置位于 configs/*.local.*，不会提交",
        2,
    )


def _base_command(root: Path, subcommand: str) -> list[str]:
    return ["{python}", str(CRAWLER_SCRIPT), "--project", str(root), subcommand]


def _read_source_receipt(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"WikiWiki source receipt 不可读：{path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"WikiWiki source receipt 根节点无效：{path}")
    return payload


def _parse(args: list[str]) -> tuple[str, bool, bool, int | None] | dict:
    values = list(args)
    action = "crawl"
    if values and values[0] in {"session", "config", "smoke"}:
        action = values[0]
        values = values[1:]

    full = False
    refresh = False
    daily_limit: int | None = None
    index = 0
    while index < len(values):
        item = values[index]
        if item == "--full":
            full = True
        elif item == "--refresh":
            refresh = True
        elif item == "--daily-limit":
            if index + 1 >= len(values):
                return _usage_error("--daily-limit 缺少数值")
            try:
                daily_limit = int(values[index + 1])
            except ValueError:
                return _usage_error("--daily-limit 必须是整数")
            if daily_limit < 0:
                return _usage_error("--daily-limit 必须大于等于 0")
            index += 1
        else:
            return _usage_error(f"未知 WikiWiki 参数：{item}")
        index += 1

    if action == "session" and (full or refresh or daily_limit is not None):
        return _usage_error("session 只用于人工恢复浏览器会话，不接受 --full、--refresh 或 --daily-limit")
    if action == "config" and (full or refresh or daily_limit is not None):
        return _usage_error("config 只用于生成/查看本地配置路径，不接受 --full、--refresh 或 --daily-limit")
    if action == "smoke" and full:
        return _usage_error("smoke 是 3 条数据链路验证入口，不接受 --full")
    if action == "smoke" and daily_limit is None:
        daily_limit = 3
    return action, full, refresh, daily_limit


def run(root: Path, args: list[str], config: dict, loader=None) -> dict:
    parsed = _parse(args)
    if isinstance(parsed, dict):
        return parsed
    config_result = _ensure_config(root)

    action, full, refresh, daily_limit = parsed
    if action == "config":
        if config_result is not None:
            # Config bootstrap is intentionally a stopping point for human review.
            return config_result
        return result(
            "成功",
            "WikiWiki 本地浏览器会话配置已存在",
            [f"本地配置：{LOCAL_CONFIG_PATH.as_posix()}", f"默认配置：{DEFAULT_CONFIG_PATH.as_posix()}"],
            [],
            "需要调整时编辑 configs/wikiwiki-crawler.local.json；然后执行 ./flow wikiwiki --full",
            "无需回滚；本地配置位于 configs/*.local.*，不会提交",
        )
    if config_result is not None:
        return config_result

    completed: list[str] = []

    if action == "session":
        log_path = run_logged(root, _base_command(root, "session"), "wikiwiki-session")
        return result(
            "成功",
            "WikiWiki 浏览器会话入口已执行",
            [f"会话日志：{log_path.relative_to(root)}"],
            [],
            "重新执行 ./flow wikiwiki",
            "无需回滚；浏览器 Profile 与 Cookie 位于 .flow/local",
        )

    catalog_command = _base_command(root, "catalog") + ["--kind", "all"]
    crawl_command = _base_command(root, "crawl")

    catalog_refresh = refresh or full
    crawl_refresh = refresh and not full
    if full:
        daily_limit = FULL_REFRESH_LIMIT if daily_limit is None else daily_limit
    if catalog_refresh:
        catalog_command.append("--refresh")
    if crawl_refresh:
        crawl_command.append("--refresh")
    if daily_limit is not None:
        crawl_command += ["--daily-limit", str(daily_limit)]

    catalog_log = run_logged(root, catalog_command, "wikiwiki-catalog")
    completed.append(f"三索引刷新/复用完成（ship/equipment/improvement）：{catalog_log.relative_to(root)}")
    crawl_log = run_logged(root, crawl_command, "wikiwiki-crawl")
    completed.append(f"装备详情浏览器会话抓取完成：{crawl_log.relative_to(root)}")
    receipt_path = root / ".flow/local/wikiwiki-crawler/source-receipt.json"
    if receipt_path.is_file():
        receipt = _read_source_receipt(receipt_path)
        completed.append("source receipt：.flow/local/wikiwiki-crawler/source-receipt.json")
    else:
        receipt = {}
        if full:
            return result(
                "失败",
                "WikiWiki full source acquisition 未生成 source receipt",
                completed,
                ["缺少 .flow/local/wikiwiki-crawler/source-receipt.json"],
                "继续执行 ./flow wikiwiki --full；不要先执行 ./flow run",
                "无需回滚；source cache 与断点保留在 .flow/local",
                75,
            )
    if receipt and not receipt.get("ready"):
        equipment = receipt.get("details", {}).get("equipment", {}) if isinstance(receipt.get("details"), dict) else {}
        incomplete = [
            f"equipmentDetails={equipment.get('status') or 'unknown'}",
            f"remaining={equipment.get('remaining', 'unknown')}",
            f"failed={equipment.get('failed', 'unknown')}",
            f"stopReason={equipment.get('stopReason') or 'none'}",
        ]
        if full:
            return result(
                "失败",
                "WikiWiki full source acquisition 未完成",
                completed,
                incomplete,
                "继续执行 ./flow wikiwiki --full；不要先执行 ./flow run",
                "无需回滚；source cache 与断点保留在 .flow/local",
                75,
            )
        if action == "smoke":
            return result(
                "成功",
                "WikiWiki 3 条数据链路验证已完成，但 source receipt 尚未 ready",
                completed,
                incomplete,
                "继续执行 ./flow wikiwiki --full；receipt ready 后再执行 ./flow run",
                "无需回滚；source cache 与断点保留在 .flow/local",
            )
        return result(
            "成功",
            "WikiWiki 日常 source acquisition 已推进，但 source receipt 尚未 ready",
            completed,
            incomplete,
            "继续执行 ./flow wikiwiki --full；receipt ready 后再执行 ./flow run",
            "无需回滚；source cache 与断点保留在 .flow/local",
        )

    next_step = "执行 ./flow run 进行本地解析、交叉验证与 after check"
    if action == "smoke":
        current = "WikiWiki 3 条数据链路验证完成"
        next_step = "继续执行 ./flow wikiwiki --full；receipt ready 后再执行 ./flow run"
    elif full:
        current = "WikiWiki 三索引与装备详情全量浏览器刷新完成"
    elif refresh:
        current = "WikiWiki 三索引与装备详情强制刷新完成"
    else:
        current = "WikiWiki 三索引与装备详情日常浏览器刷新完成"
    return result(
        "成功",
        current,
        completed,
        [],
        next_step,
        "无需回滚；如抓取中断，修复浏览器会话后重新执行 ./flow wikiwiki",
    )
