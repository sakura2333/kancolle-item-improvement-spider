import unittest
from pathlib import Path
from unittest.mock import patch

from lxml import etree

from pojo.improvement import ConsumeItem
from service.akashi_list.detail_stage_parser import (
    _download_useitem_image,
    download_detail_equipment_image,
)


class AkashiImageDownloadTest(unittest.TestCase):
    def test_equipment_image_uses_equipment_asset_namespace(self):
        equipment = ConsumeItem(id=123, count=1, type=0)

        with patch("service.akashi_list.detail_stage_parser.download_pic") as download_mock:
            _download_useitem_image(equipment, "https://example.test/equipment.png")

        download_mock.assert_called_once_with(
            url="https://example.test/equipment.png",
            save_path="cache/equipment-images/123.png",
        )

    def test_useitem_image_uses_picture_downloader(self):
        useitem = ConsumeItem(id=91, count=1, type=1)

        with patch("service.akashi_list.detail_stage_parser.download_pic") as download_mock:
            _download_useitem_image(useitem, "https://example.test/useitem.png")

        download_mock.assert_called_once_with(
            url="https://example.test/useitem.png",
            save_path="cache/images/91.png",
        )

    def test_detail_page_primary_equipment_image_is_downloaded(self):
        page = Path("tests/fixtures/akashi/w061.html").read_text(encoding="utf-8")
        page_node = etree.HTML(page)

        with patch("service.akashi_list.detail_stage_parser.download_pic") as download_mock:
            download_detail_equipment_image(61, page_node)

        download_mock.assert_called_once_with(
            url="https://aiacdn.contents-stg.site/img/weapon061_260.png",
            save_path="cache/equipment-images/61.png",
        )


if __name__ == "__main__":
    unittest.main()
