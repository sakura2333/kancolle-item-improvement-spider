from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlencode, urljoin

from PIL import Image

from service.data_package.package_paths import CACHE_EQUIPMENT_IMAGE_DIR
from util.cache import download_pic
from util.start2.start2_item_utils import start2ItemUtils
from util.start2.start2_use_item_utils import start2ConsumeUseUtils

_RESOURCE = (
    6657, 5699, 3371, 8909, 7719, 6229, 5449, 8561, 2987, 5501,
    3127, 9319, 4365, 9811, 9927, 2423, 3439, 1865, 5925, 4409,
    5509, 1517, 9695, 9255, 5325, 3691, 5519, 6949, 5607, 9539,
    4133, 7795, 5465, 2659, 6381, 6875, 4019, 9195, 5645, 2887,
    1213, 1815, 8671, 3015, 3147, 2991, 7977, 7045, 1619, 7909,
    4451, 6573, 4545, 8251, 5983, 2849, 7249, 7449, 9477, 5963,
    2711, 9019, 7375, 2201, 5631, 4893, 7653, 3719, 8819, 5839,
    1853, 9843, 9119, 7023, 5681, 2345, 9873, 6349, 9315, 3795,
    9737, 4633, 4173, 7549, 7171, 6147, 4723, 5039, 2723, 7815,
    6201, 5999, 5339, 4431, 2911, 4435, 3611, 4423, 9517, 3243,
)
_DEFAULT_BASE_URLS = (
    "https://w15p.kancolle-server.com/",
)
_USEITEM_CARD_EXCLUDED = {2, 10, 31, 32, 33, 34, 44, 49, 50, 51, 53, 76}
WEBP_QUALITY = 93
WEBP_ALPHA_QUALITY = 100
WEBP_METHOD = 6
EQUIPMENT_CARD_SIZE = (390, 390)


def _resource_code(item_id: int, resource_type: str) -> str:
    key = sum(ord(char) for char in resource_type)
    index = (key + item_id * len(resource_type)) % len(_RESOURCE)
    return str(17 * (item_id + 7) * _RESOURCE[index] % 8973 + 1000)


def _base_urls() -> tuple[str, ...]:
    configured = os.getenv("KANCOLLE_ASSET_BASE_URLS", "").strip()
    if not configured:
        return _DEFAULT_BASE_URLS
    values = tuple(
        value.strip().rstrip("/") + "/"
        for value in configured.split(",")
        if value.strip()
    )
    if not values:
        raise ValueError("KANCOLLE_ASSET_BASE_URLS does not contain a usable URL")
    return values


def _equipment_source_cache_path(
    equipment_id: int,
    api_version: object | None,
) -> str:
    version = (
        str(api_version).strip()
        if api_version not in (None, "")
        else "unversioned"
    )
    safe_version = (
        re.sub(r"[^0-9A-Za-z._-]+", "_", version).strip("._-")
        or "unversioned"
    )
    return f"cache/official/equip/{int(equipment_id)}/{safe_version}.png"


def equipment_card_paths(
    equipment_id: int,
    api_version: object | None = None,
) -> list[str]:
    item_id = int(equipment_id)
    code = _resource_code(item_id, "slot_card")
    relative = f"kcs2/resources/slot/card/{item_id:04d}_{code}.png"
    if api_version not in (None, ""):
        relative = f"{relative}?{urlencode({'version': str(api_version)})}"
    return [urljoin(base, relative) for base in _base_urls()]


def useitem_card_paths(useitem_id: int) -> list[str]:
    item_id = int(useitem_id)
    relatives: list[str] = []
    if item_id not in _USEITEM_CARD_EXCLUDED:
        relatives.append(f"kcs2/resources/useitem/card/{item_id:03d}.png")
    if item_id < 49 and item_id != 10:
        relatives.append(f"kcs2/resources/useitem/card_/{item_id:03d}.png")
    return [urljoin(base, relative) for relative in relatives for base in _base_urls()]


def _download_first(urls: list[str], save_path: str) -> Path:
    if not urls:
        raise RuntimeError(f"no official KanColle asset URL is defined for {save_path}")
    errors: list[str] = []
    for url in urls:
        try:
            return Path(download_pic(url=url, save_path=save_path))
        except RuntimeError as error:
            errors.append(f"{url}: {error}")
    raise RuntimeError("all official KanColle asset sources failed: " + " | ".join(errors))


def _validate_png(source: Path, *, expected_size: tuple[int, int] | None = None) -> Path:
    try:
        with Image.open(source) as image:
            image.load()
            if image.format != "PNG":
                raise RuntimeError(f"official asset is not PNG: {source}")
            if expected_size is not None and image.size != expected_size:
                raise RuntimeError(
                    f"official asset has unexpected size {image.size}: {source}"
                )
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError(f"invalid official PNG asset: {source}: {error}") from error
    return source


def _is_valid_equipment_webp(target: Path) -> bool:
    if not target.is_file():
        return False
    try:
        with Image.open(target) as image:
            if image.format != "WEBP" or image.size != EQUIPMENT_CARD_SIZE:
                return False
            image.verify()
    except Exception:
        return False
    return True


def _encode_webp(source: Path, target: Path) -> Path:
    if (
        target.exists()
        and target.stat().st_mtime_ns >= source.stat().st_mtime_ns
        and _is_valid_equipment_webp(target)
    ):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    _validate_png(source, expected_size=EQUIPMENT_CARD_SIZE)
    try:
        with Image.open(source) as image:
            image.load()
            image.convert("RGBA").save(
                target,
                format="WEBP",
                quality=WEBP_QUALITY,
                alpha_quality=WEBP_ALPHA_QUALITY,
                method=WEBP_METHOD,
                exact=True,
            )
    except Exception as error:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"failed to encode equipment WebP: {source}: {error}") from error
    return target


def download_equipment_card(equipment_id: int) -> Path:
    item_id = int(equipment_id)
    record = start2ItemUtils.find_by_id(item_id)
    if record is None:
        raise RuntimeError(f"equipment {item_id} is absent from api_mst_slotitem")
    api_version = record.get("api_version")
    source = _download_first(
        equipment_card_paths(item_id, api_version),
        _equipment_source_cache_path(item_id, api_version),
    )
    return _encode_webp(source, CACHE_EQUIPMENT_IMAGE_DIR / f"{item_id}.webp")


def download_useitem_card(useitem_id: int) -> Path:
    item_id = int(useitem_id)
    if start2ConsumeUseUtils.find_by_id(item_id) is None:
        raise RuntimeError(f"useitem {item_id} is absent from api_mst_useitem")
    source = _download_first(
        useitem_card_paths(item_id),
        f"cache/useitem/{item_id}.png",
    )
    return _validate_png(source)

def required_asset_ids(items) -> dict[str, list[int]]:
    """Collect image IDs from canonical improvement routes.

    Akashi parsing only produces recipe facts. Image acquisition starts after
    those facts have been converted into canonical routes, so source HTML and
    image transport remain independent.
    """

    equipment_ids: set[int] = set()
    useitem_ids: set[int] = set()
    for item in items:
        item_id = int(getattr(item, "id", 0) or 0)
        if item_id > 0:
            equipment_ids.add(item_id)
        for improvement in getattr(item, "improvement_list", ()) or ():
            for stage in getattr(improvement, "stage_list", ()) or ():
                target = getattr(stage, "target_weapon", None)
                target_id = int(getattr(target, "id", 0) or 0)
                if target_id > 0:
                    equipment_ids.add(target_id)
                for consumable in getattr(stage, "consumable_list", ()) or ():
                    consumable_id = int(getattr(consumable, "id", 0) or 0)
                    if consumable_id <= 0:
                        continue
                    if int(getattr(consumable, "type", -1)) == 0:
                        equipment_ids.add(consumable_id)
                    elif int(getattr(consumable, "type", -1)) == 1:
                        useitem_ids.add(consumable_id)
    return {
        "equipmentIds": sorted(equipment_ids),
        "useitemIds": sorted(useitem_ids),
    }


def acquire_required_assets(items) -> dict[str, object]:
    """Acquire all official images required by canonical improvement routes."""

    required = required_asset_ids(items)
    for equipment_id in required["equipmentIds"]:
        download_equipment_card(equipment_id)
    for useitem_id in required["useitemIds"]:
        download_useitem_card(useitem_id)
    return {
        **required,
        "equipmentCount": len(required["equipmentIds"]),
        "useitemCount": len(required["useitemIds"]),
    }

