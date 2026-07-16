from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Iterable

from service.data_package.package_paths import (
    CACHE_EQUIPMENT_IMAGE_DIR,
    CACHE_IMAGE_DIR,
    IMPROVEMENT2_COMPAT_DIR,
    PACKAGE_DIR,
    STATIC_EQUIPMENT_IMAGE_DIR,
    STATIC_IMAGE_DIR,
)

def _copy_file(source: Path, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

def _clear_regenerated():
    # Improvement projections and icons are owned locally and can always be
    # regenerated. External equipment datasets are intentionally preserved
    # until their replacement source has been fetched and parsed successfully.
    for relative in ("assets/useitems", "assets/equipment"):
        legacy_path = PACKAGE_DIR / relative
        if legacy_path.exists():
            shutil.rmtree(legacy_path)
    for relative in ("improvement", "assets/useitem", "assets/equip", "audit"):
        path = PACKAGE_DIR / relative
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
    if IMPROVEMENT2_COMPAT_DIR.exists():
        shutil.rmtree(IMPROVEMENT2_COMPAT_DIR)
    IMPROVEMENT2_COMPAT_DIR.mkdir(parents=True, exist_ok=True)
    (PACKAGE_DIR / "equipment").mkdir(parents=True, exist_ok=True)

def _read_nedb(path: Path) -> Iterable[dict]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)

def _required_useitem_ids(detail_path: Path) -> list[int]:
    required: set[int] = set()
    for item in _read_nedb(detail_path):
        for route in item.get("improvementList", []):
            for stage in route.get("stageList", []):
                for consumable in stage.get("consumables", []):
                    if consumable.get("type") == 1:
                        try:
                            item_id = int(consumable.get("id"))
                        except (TypeError, ValueError):
                            continue
                        if item_id > 0:
                            required.add(item_id)
    return sorted(required)

def _improvement_projection_metrics(detail_path: Path) -> dict[str, int]:
    records = list(_read_nedb(detail_path))
    routes = [
        route
        for record in records
        for route in record.get("improvementList", [])
        if isinstance(route, dict)
    ]
    return {
        "detailRecordCount": len(records),
        "effectExpectationAvailableCount": sum(
            1 for record in records
            if record.get("effectSource", {}).get("status") == "ok"
        ),
        "effectExpectationUnavailableCount": sum(
            1 for record in records
            if record.get("effectSource", {}).get("status") == "unavailable"
        ),
        "routeCount": len(routes),
        "stepCount": sum(
            len(route.get("stepList", []))
            for route in routes
            if isinstance(route.get("stepList"), list)
        ),
        "upgradeAvailableCount": sum(
            1
            for route in routes
            for step in route.get("stepList", [])
            if isinstance(step, dict)
            and step.get("action") == "upgrade"
            and step.get("available") is True
        ),
    }

def _copy_icon_directory(source_dir: Path, target_dir: Path):
    if not source_dir.exists():
        return
    for image in sorted(source_dir.glob("*.png")):
        _copy_file(image, target_dir / image.name)

def _promote_cached_icons():
    """Persist newly discovered icons outside the ignored HTTP cache.

    Runtime cache is intentionally not committed. Promoting numeric PNGs into
    data/assets makes the next clean checkout reproducible and lets the release
    commit carry newly referenced use-item assets.
    """

    _copy_icon_directory(CACHE_IMAGE_DIR, STATIC_IMAGE_DIR)


def _promote_cached_equipment_images():
    """Persist AkashiList equipment images into a stable asset directory."""

    _copy_icon_directory(CACHE_EQUIPMENT_IMAGE_DIR, STATIC_EQUIPMENT_IMAGE_DIR)

