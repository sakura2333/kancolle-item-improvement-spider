from __future__ import annotations

import os
from typing import Any, Iterable

from util.start2.catalog import IndexedCatalog, LazyJsonCatalog
from util.start2.config import start2_dir

Item = dict[str, Any]


class Start2ItemUtils(IndexedCatalog):
    """Indexed start2 equipment catalog."""

    def __init__(self, items: Iterable[Item]):
        super().__init__(items)


class LazyStart2ItemUtils(LazyJsonCatalog[Start2ItemUtils]):
    def __init__(self, json_path: str):
        super().__init__(json_path, Start2ItemUtils)


start2ItemUtils = LazyStart2ItemUtils(
    os.path.join(start2_dir, "api_mst_slotitem.json")
)


if __name__ == "__main__":
    for name in ("14cm連装砲改", "14cm連装砲改二"):
        print(start2ItemUtils.find_by_name(name))
    print(start2ItemUtils.find_by_id(407))
