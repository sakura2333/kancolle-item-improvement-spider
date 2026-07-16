import unittest
from unittest.mock import patch

from pojo.improvement import ConsumeItem
from service.akashi_list.detail_stage_parser import _download_useitem_image


class AkashiImageDownloadTest(unittest.TestCase):
    def test_equipment_image_is_not_downloaded(self):
        equipment = ConsumeItem(id=123, count=1, type=0)

        with patch("service.akashi_list.detail_stage_parser.download_pic") as download_mock:
            _download_useitem_image(equipment, "https://example.test/equipment.png")

        download_mock.assert_not_called()

    def test_useitem_image_uses_picture_downloader(self):
        useitem = ConsumeItem(id=91, count=1, type=1)

        with patch("service.akashi_list.detail_stage_parser.download_pic") as download_mock:
            _download_useitem_image(useitem, "https://example.test/useitem.png")

        download_mock.assert_called_once_with(
            url="https://example.test/useitem.png",
            save_path="cache/images/91.png",
        )


if __name__ == "__main__":
    unittest.main()
