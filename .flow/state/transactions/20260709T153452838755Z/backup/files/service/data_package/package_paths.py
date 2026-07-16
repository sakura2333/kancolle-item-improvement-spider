from pathlib import Path

from configs.path import PROJECT_ROOT, get_dist_dir, get_source_cache_dir

PACKAGE_SOURCE_DIR = Path(PROJECT_ROOT) / "packages" / "kancolle-data"
PACKAGE_DIR = Path(get_dist_dir("packages")) / "kancolle-data"
SOURCE_ROOT = Path(get_dist_dir("data-pipeline")) / "sources"
IMPROVEMENT_DIR = Path(get_dist_dir("data-pipeline")) / "improvement"
CACHE_IMAGE_DIR = Path(get_source_cache_dir("cache/images"))
CACHE_EQUIPMENT_IMAGE_DIR = Path(get_source_cache_dir("cache/equipment-images"))
STATIC_IMAGE_DIR = Path(get_dist_dir("data-pipeline/assets/useitems"))
STATIC_EQUIPMENT_IMAGE_DIR = Path(get_dist_dir("data-pipeline/assets/equipment"))
AKASHI_URL = "https://akashi-list.me/"
AKASHI_METADATA_PATH = SOURCE_ROOT / "akashi-list" / "metadata.json"
COMPATIBILITY_DIR = PACKAGE_DIR / "compat"
IMPROVEMENT2_COMPAT_DIR = COMPATIBILITY_DIR / "poi-plugin-item-improvement2"
