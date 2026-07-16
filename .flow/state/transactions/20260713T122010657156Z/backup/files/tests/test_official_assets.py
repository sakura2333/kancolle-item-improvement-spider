import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from service.data_package import official_assets
from service.data_package.improvement_record import ImprovementVO, WeaponItemVO
from service.data_package.validation.assets import _validate_equipment_images
from service.data_package.validation.common import QualityGateError
from service.improvement.model import ConsumeItem, ImprovementStage, TargetWeapon


class OfficialAssetTest(unittest.TestCase):
    def test_equipment_resource_code_matches_known_cards(self):
        with patch.dict(os.environ, {"KANCOLLE_ASSET_BASE_URLS": "https://assets.test/"}):
            self.assertEqual(
                official_assets.equipment_card_paths(162, "1"),
                ["https://assets.test/kcs2/resources/slot/card/0162_3810.png?version=1"],
            )
            self.assertEqual(
                official_assets.equipment_card_paths(165),
                ["https://assets.test/kcs2/resources/slot/card/0165_3477.png"],
            )

    def test_useitem_legacy_and_current_paths_follow_official_layout(self):
        with patch.dict(os.environ, {"KANCOLLE_ASSET_BASE_URLS": "https://assets.test/"}):
            self.assertEqual(
                official_assets.useitem_card_paths(2),
                ["https://assets.test/kcs2/resources/useitem/card_/002.png"],
            )
            self.assertEqual(
                official_assets.useitem_card_paths(88),
                ["https://assets.test/kcs2/resources/useitem/card/088.png"],
            )

    def test_equipment_card_is_encoded_as_webp_quality_93(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "cache" / "official" / "equip" / "162.png"
            source.parent.mkdir(parents=True)
            Image.new("RGBA", (390, 390), (120, 80, 40, 180)).save(source, "PNG")
            target = root / "cache" / "equip" / "162.webp"
            with patch.object(official_assets, "CACHE_EQUIPMENT_IMAGE_DIR", target.parent), patch.object(
                official_assets, "download_pic", return_value=str(source)
            ) as download, patch.object(
                official_assets,
                "start2ItemUtils",
                SimpleNamespace(find_by_id=lambda _item_id: {"api_id": 162, "api_version": "1"}),
            ):
                actual = official_assets.download_equipment_card(162)
            self.assertEqual(actual, target)
            self.assertEqual(
                download.call_args.kwargs["save_path"],
                "cache/official/equip/162/1.png",
            )
            self.assertTrue(target.read_bytes().startswith(b"RIFF"))
            with Image.open(target) as image:
                self.assertEqual(image.format, "WEBP")
                self.assertEqual(image.size, (390, 390))

    def test_invalid_cached_webp_is_reencoded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "162.png"
            target = root / "162.webp"
            Image.new("RGBA", (390, 390), (120, 80, 40, 180)).save(source, "PNG")
            target.write_bytes(b"not-webp")
            target.touch()
            actual = official_assets._encode_webp(source, target)
            self.assertEqual(actual, target)
            with Image.open(target) as image:
                self.assertEqual(image.format, "WEBP")
                self.assertEqual(image.size, (390, 390))

    def test_equipment_card_rejects_unexpected_dimensions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "162.png"
            target = root / "162.webp"
            Image.new("RGBA", (130, 130), (120, 80, 40, 180)).save(source, "PNG")
            with self.assertRaisesRegex(RuntimeError, "unexpected size"):
                official_assets._encode_webp(source, target)
            self.assertFalse(target.exists())

    def test_equipment_source_cache_key_tracks_api_version(self):
        self.assertEqual(
            official_assets._equipment_source_cache_path(162, "3.2/preview"),
            "cache/official/equip/162/3.2_preview.png",
        )
        self.assertEqual(
            official_assets._equipment_source_cache_path(162, None),
            "cache/official/equip/162/unversioned.png",
        )

    def test_useitem_card_keeps_png(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "88.png"
            Image.new("RGBA", (270, 270), (20, 40, 60, 255)).save(source, "PNG")
            with patch.object(
                official_assets,
                "start2ConsumeUseUtils",
                SimpleNamespace(find_by_id=lambda _item_id: {"api_id": 88}),
            ), patch.object(official_assets, "download_pic", return_value=str(source)) as download:
                actual = official_assets.download_useitem_card(88)
            self.assertEqual(actual, source)
            self.assertEqual(download.call_args.kwargs["save_path"], "cache/useitem/88.png")

    def test_packaged_equipment_validation_requires_390_webp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            valid = directory / "162.webp"
            Image.new("RGBA", (390, 390), (120, 80, 40, 180)).save(
                valid,
                "WEBP",
                quality=93,
            )
            self.assertEqual(_validate_equipment_images(directory), {162})

            invalid = directory / "163.webp"
            Image.new("RGBA", (130, 130), (120, 80, 40, 180)).save(
                invalid,
                "WEBP",
                quality=93,
            )
            with self.assertRaisesRegex(QualityGateError, "390x390"):
                _validate_equipment_images(directory)

    def test_useitem_download_rejects_non_png_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "88.png"
            source.write_text("not an image", encoding="utf-8")
            with patch.object(
                official_assets,
                "start2ConsumeUseUtils",
                SimpleNamespace(find_by_id=lambda _item_id: {"api_id": 88}),
            ), patch.object(official_assets, "download_pic", return_value=str(source)):
                with self.assertRaisesRegex(RuntimeError, "invalid official PNG"):
                    official_assets.download_useitem_card(88)

    def test_required_asset_stage_collects_canonical_route_ids_once(self):
        stage = ImprovementStage(
            target_weapon=TargetWeapon(id=200),
            consumable_list=[
                ConsumeItem(id=123, count=2, type=0),
                ConsumeItem(id=91, count=1, type=1),
                ConsumeItem(id=123, count=1, type=0),
            ],
        )
        items = [
            WeaponItemVO(
                id=61,
                improvement_list=[ImprovementVO(stage_list=[stage])],
            )
        ]
        self.assertEqual(
            official_assets.required_asset_ids(items),
            {"equipmentIds": [61, 123, 200], "useitemIds": [91]},
        )
        with patch.object(official_assets, "download_equipment_card") as equipment, patch.object(
            official_assets, "download_useitem_card"
        ) as useitem:
            summary = official_assets.acquire_required_assets(items)
        self.assertEqual(
            [call.args[0] for call in equipment.call_args_list],
            [61, 123, 200],
        )
        useitem.assert_called_once_with(91)
        self.assertEqual(summary["equipmentCount"], 3)
        self.assertEqual(summary["useitemCount"], 1)

    def test_missing_start2_records_are_rejected(self):
        with patch.object(
            official_assets,
            "start2ItemUtils",
            SimpleNamespace(find_by_id=lambda _item_id: None),
        ):
            with self.assertRaisesRegex(RuntimeError, "absent from api_mst_slotitem"):
                official_assets.download_equipment_card(9999)
        with patch.object(
            official_assets,
            "start2ConsumeUseUtils",
            SimpleNamespace(find_by_id=lambda _item_id: None),
        ):
            with self.assertRaisesRegex(RuntimeError, "absent from api_mst_useitem"):
                official_assets.download_useitem_card(9999)


if __name__ == "__main__":
    unittest.main()
