from __future__ import annotations

from pathlib import Path

from .common import QualityGateError

def _validate_icons(directory: Path) -> set[int]:
    icons = sorted(directory.glob("*.png")) if directory.exists() else []
    icon_ids: set[int] = set()
    for icon in icons:
        data = icon.read_bytes()
        if len(data) < 100 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise QualityGateError(f"invalid PNG asset: {icon}")
        if not icon.stem.isdigit():
            raise QualityGateError(f"use-item icon filename must be numeric: {icon.name}")
        icon_id = int(icon.stem)
        if icon_id in icon_ids:
            raise QualityGateError(f"duplicate use-item icon id: {icon_id}")
        icon_ids.add(icon_id)
    return icon_ids
