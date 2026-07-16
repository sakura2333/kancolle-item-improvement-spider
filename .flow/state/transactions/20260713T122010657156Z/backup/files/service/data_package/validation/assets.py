from __future__ import annotations

from pathlib import Path
from typing import Callable

from PIL import Image

from .common import QualityGateError


def _validate_assets(
    directory: Path,
    *,
    suffix: str,
    valid_header: Callable[[bytes], bool],
    label: str,
) -> set[int]:
    assets = sorted(directory.glob(f"*{suffix}")) if directory.exists() else []
    asset_ids: set[int] = set()
    for asset in assets:
        data = asset.read_bytes()
        if len(data) < 100 or not valid_header(data):
            raise QualityGateError(f"invalid {label} asset: {asset}")
        if not asset.stem.isdigit():
            raise QualityGateError(f"{label} filename must be numeric: {asset.name}")
        asset_id = int(asset.stem)
        if asset_id in asset_ids:
            raise QualityGateError(f"duplicate {label} id: {asset_id}")
        asset_ids.add(asset_id)
    return asset_ids


def _validate_icons(directory: Path) -> set[int]:
    return _validate_assets(
        directory,
        suffix=".png",
        valid_header=lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
        label="use-item icon",
    )


def _validate_equipment_images(directory: Path) -> set[int]:
    image_ids = _validate_assets(
        directory,
        suffix=".webp",
        valid_header=lambda data: data.startswith(b"RIFF") and data[8:12] == b"WEBP",
        label="equipment image",
    )
    for asset in sorted(directory.glob("*.webp")):
        try:
            with Image.open(asset) as image:
                if image.format != "WEBP" or image.size != (390, 390):
                    raise QualityGateError(
                        f"equipment image must be 390x390 WebP: {asset}"
                    )
                image.verify()
        except QualityGateError:
            raise
        except Exception as error:
            raise QualityGateError(f"invalid equipment WebP asset: {asset}: {error}") from error
    return image_ids
