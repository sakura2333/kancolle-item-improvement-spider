import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AkashiImageDownloadBoundaryTest(unittest.TestCase):
    def test_akashi_parsers_do_not_acquire_images(self):
        for relative in (
            "service/akashi_list/detail_stage_parser.py",
            "service/akashi_list/akashi_detail_processor.py",
        ):
            source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("official_assets", source, relative)
            self.assertNotIn("download_equipment_card", source, relative)
            self.assertNotIn("download_useitem_card", source, relative)

    def test_official_asset_stage_runs_after_canonical_route_conversion(self):
        source = (PROJECT_ROOT / "script/project/akashi_command.py").read_text(
            encoding="utf-8"
        )
        conversion = source.index("vo_list = convert_vo(detail_processor.result)")
        acquisition = source.index("official_assets = acquire_required_assets(vo_list)")
        self.assertLess(conversion, acquisition)

    def test_akashi_html_image_urls_are_not_parsed(self):
        sources = "\n".join(
            (PROJECT_ROOT / relative).read_text(encoding="utf-8")
            for relative in (
                "service/akashi_list/detail_stage_parser.py",
                "service/akashi_list/akashi_detail_processor.py",
            )
        )
        self.assertNotIn("data-src", sources)
        self.assertNotIn("akashi.example", sources)


if __name__ == "__main__":
    unittest.main()
