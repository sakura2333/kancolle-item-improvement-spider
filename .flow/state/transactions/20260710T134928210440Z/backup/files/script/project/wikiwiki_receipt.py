from __future__ import annotations

"""WikiWiki source acquisition receipt inspection helpers.

The receipt is local runtime evidence under ``.flow/local``.  It is not part of
Flow content identity, but Flow commands should still sense it so users can see
whether browser-session acquisition is missing, incomplete, or ready for the
offline strict parser.
"""

import json
from pathlib import Path
from typing import Any

WIKIWIKI_SOURCE_RECEIPT_PATH = Path(".flow/local/wikiwiki-crawler/source-receipt.json")


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def read_receipt(root: Path) -> dict[str, Any] | None:
    path = root / WIKIWIKI_SOURCE_RECEIPT_PATH
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "_flowReceiptStatus": "invalid",
            "_flowReceiptError": f"不可读：{type(exc).__name__}: {exc}",
        }
    if not isinstance(value, dict):
        return {
            "_flowReceiptStatus": "invalid",
            "_flowReceiptError": "JSON 根节点不是对象",
        }
    return value


def _index_statuses(receipt: dict[str, Any]) -> list[str]:
    indexes = receipt.get("indexes") if isinstance(receipt.get("indexes"), dict) else {}
    values: list[str] = []
    for kind in ("ship", "equipment", "improvement"):
        entry = indexes.get(kind) if isinstance(indexes, dict) else None
        if isinstance(entry, dict):
            values.append(f"{kind}={entry.get('status') or 'unknown'}")
        else:
            values.append(f"{kind}=missing")
    return values


def _equipment_line(receipt: dict[str, Any]) -> str:
    details = receipt.get("details") if isinstance(receipt.get("details"), dict) else {}
    equipment = details.get("equipment") if isinstance(details, dict) else None
    if not isinstance(equipment, dict):
        return "equipmentDetails=missing"
    fields = [
        f"equipmentDetails={equipment.get('status') or 'unknown'}",
        f"selected={equipment.get('selected', 'unknown')}",
        f"completed={equipment.get('completed', 'unknown')}",
        f"remaining={equipment.get('remaining', 'unknown')}",
        f"failed={equipment.get('failed', 'unknown')}",
        f"sourceExcluded={equipment.get('sourceExcluded', 'unknown')}",
        f"stopReason={equipment.get('stopReason') or 'none'}",
    ]
    next_equipment = equipment.get("nextEquipmentId")
    if next_equipment is not None:
        fields.append(f"nextEquipmentId={next_equipment}")
    return " ".join(fields)


def summary(root: Path) -> dict[str, Any]:
    path = root / WIKIWIKI_SOURCE_RECEIPT_PATH
    receipt = read_receipt(root)
    if receipt is None:
        return {
            "status": "missing",
            "ready": False,
            "path": path,
            "displayPath": _display_path(root, path),
            "line": f"WikiWiki source receipt 缺失：{_display_path(root, path)}",
            "details": [],
            "next": "./flow wikiwiki --full",
            "receipt": None,
        }
    if receipt.get("_flowReceiptStatus") == "invalid":
        error = str(receipt.get("_flowReceiptError") or "invalid")
        return {
            "status": "invalid",
            "ready": False,
            "path": path,
            "displayPath": _display_path(root, path),
            "line": f"WikiWiki source receipt 无效：{error}",
            "details": [f"路径：{_display_path(root, path)}"],
            "next": "删除或修复 source receipt 后执行 ./flow wikiwiki --full",
            "receipt": receipt,
        }
    schema = receipt.get("schemaVersion")
    source = receipt.get("source")
    schema_valid = schema == 1 and source == "wikiwiki-jp"
    ready = bool(receipt.get("ready")) and schema_valid
    status = "ready" if ready else "not-ready"
    if not schema_valid:
        status = "invalid"
    line = (
        "WikiWiki source receipt ready"
        if ready
        else "WikiWiki source receipt 尚未 ready"
    )
    if not schema_valid:
        line = "WikiWiki source receipt schema/source 无效"
    details = [
        f"路径：{_display_path(root, path)}",
        "indexes：" + " ".join(_index_statuses(receipt)),
        _equipment_line(receipt),
    ]
    return {
        "status": status,
        "ready": ready,
        "path": path,
        "displayPath": _display_path(root, path),
        "line": line + f"：{_display_path(root, path)}",
        "details": details,
        "next": "./flow run" if ready else "./flow wikiwiki --full",
        "receipt": receipt,
    }


def is_ready(root: Path) -> bool:
    return bool(summary(root)["ready"])
