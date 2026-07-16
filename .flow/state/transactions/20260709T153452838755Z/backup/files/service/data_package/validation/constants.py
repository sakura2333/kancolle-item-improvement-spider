from pathlib import Path

from configs.path import PROJECT_ROOT

DEFAULT_CONFIG_PATH = Path(PROJECT_ROOT) / "configs" / "data_quality.json"
PUBLIC_DATA_PREFIXES = (
    "improvement/",
    "compat/",
    "equipment/",
    "assets/equipment/",
    "assets/useitems/",
)
