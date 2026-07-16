#!/usr/bin/env python3
from __future__ import annotations

"""Start2/API baseline acquisition gate used by Flow smoke and WikiWiki acquisition.

Start2 is the canonical local API baseline required before WikiWiki equipment
catalog matching.  This command intentionally writes generated data under
``dist/data-pipeline/start2_data`` through ``util.start2.config.start2_dir``;
``data/`` is not restored by smoke/update workflows.
"""

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from util.start2.config import start2_dir
from util.start2.start2_utils import update_start2_if_needed

REQUIRED_FILES = (
    "api_mst_slotitem.json",
    "api_mst_ship.json",
    "api_mst_useitem.json",
)


def _display(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _validate_required_files(root: Path) -> list[str]:
    base = Path(start2_dir)
    missing: list[str] = []
    for name in REQUIRED_FILES:
        path = base / name
        if not path.is_file():
            missing.append(_display(path))
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Start2 baseline JSON 无效：{_display(path)} 第 {exc.lineno} 行：{exc.msg}") from exc
        if not isinstance(payload, list) or not payload:
            raise RuntimeError(f"Start2 baseline 内容为空或结构无效：{_display(path)}")
    return missing


def ensure_ready(*, strict: bool = True) -> None:
    if strict:
        os.environ["DATA_PACKAGE_STRICT"] = "1"
    update_start2_if_needed()
    missing = _validate_required_files(PROJECT_ROOT)
    if missing:
        raise RuntimeError(
            "Start2/API baseline 未准备好，WikiWiki catalog 不能继续。缺少：\n"
            + "\n".join(f"- {item}" for item in missing)
            + "\n请先修复网络/API baseline 更新，再重试 ./flow smoke 或 ./flow wikiwiki --full。"
        )
    print("[start2 baseline] ready=true path=" + _display(Path(start2_dir)), flush=True)


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if values and values[0] not in {"ensure", "refresh"}:
        print("用法：python3 script/project/start2_command.py [ensure|refresh]", file=sys.stderr)
        return 2
    try:
        ensure_ready(strict=True)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
