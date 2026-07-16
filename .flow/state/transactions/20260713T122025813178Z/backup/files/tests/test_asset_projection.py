import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from service.data_package import projection


class AssetProjectionTest(unittest.TestCase):
    def test_cached_icons_are_promoted_to_stable_assets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_dir = root / "cache"
            webp_dir = root / "webp"
            static_dir = root / "static"
            cache_dir.mkdir()
            webp_dir.mkdir()
            image = cache_dir / "71.png"
            webp = webp_dir / "71.webp"
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 128)
            webp.write_bytes(b"RIFF" + (128).to_bytes(4, "little") + b"WEBP" + b"x" * 128)
            with patch.object(
                projection,
                "CACHE_IMAGE_DIR",
                cache_dir,
            ), patch.object(
                projection,
                "CACHE_USEITEM_WEBP_DIR",
                webp_dir,
            ), patch.object(
                projection,
                "STATIC_IMAGE_DIR",
                static_dir,
            ):
                projection._promote_cached_icons()
            self.assertEqual((static_dir / "71.png").read_bytes(), image.read_bytes())
            self.assertEqual((static_dir / "71.webp").read_bytes(), webp.read_bytes())

    def test_equipment_promotion_replaces_legacy_png_with_webp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_dir = root / "cache"
            static_dir = root / "static"
            cache_dir.mkdir()
            static_dir.mkdir()
            (static_dir / "61.png").write_bytes(b"legacy")
            image = cache_dir / "61.webp"
            image.write_bytes(
                b"RIFF"
                + (128).to_bytes(4, "little")
                + b"WEBP"
                + b"equipment" * 16
            )
            with patch.object(
                projection,
                "CACHE_EQUIPMENT_IMAGE_DIR",
                cache_dir,
            ), patch.object(
                projection,
                "STATIC_EQUIPMENT_IMAGE_DIR",
                static_dir,
            ):
                projection._promote_cached_equipment_images()
            self.assertEqual((static_dir / "61.webp").read_bytes(), image.read_bytes())
            self.assertFalse((static_dir / "61.png").exists())


if __name__ == "__main__":
    unittest.main()
