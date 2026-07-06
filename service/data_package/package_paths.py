from pathlib import Path

from configs.path import PROJECT_ROOT, get_data_dir

PACKAGE_DIR = Path(PROJECT_ROOT) / "packages" / "kancolle-data"
SOURCE_ROOT = Path(get_data_dir("sources"))
IMPROVEMENT_DIR = Path(get_data_dir("improvement"))
CACHE_IMAGE_DIR = Path(get_data_dir("raw_data")) / "site_cache" / "cache" / "images"
STATIC_IMAGE_DIR = Path(get_data_dir("assets")) / "useitems"
AKASHI_URL = "https://akashi-list.me/"
AKASHI_METADATA_PATH = SOURCE_ROOT / "akashi-list" / "metadata.json"
COMPATIBILITY_DIR = PACKAGE_DIR / "compat"
IMPROVEMENT2_COMPAT_DIR = COMPATIBILITY_DIR / "poi-plugin-item-improvement2"
