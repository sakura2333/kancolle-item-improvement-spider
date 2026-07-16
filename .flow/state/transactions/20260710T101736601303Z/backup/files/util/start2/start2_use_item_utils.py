from __future__ import annotations

import os
import re
from typing import Any, Iterable

import mojimoji

from util.start2.catalog import IndexedCatalog, LazyJsonCatalog
from util.start2.config import start2_dir
from util.text_utils import normalize_name

Item = dict[str, Any]


class Start2UseItemUtils(IndexedCatalog):
    """Indexed start2 consumable-item catalog."""

    def __init__(self, items: Iterable[Item]):
        super().__init__(items)

    def find_by_name(self, name: str) -> Item | None:
        record = self.name_normalized_map.get(normalize_name(name))
        if record is not None:
            return record
        return self.find_one(
            lambda item: re.sub(
                r"\s+",
                "",
                mojimoji.zen_to_han(
                    str(item.get("api_name", "")), kana=True
                ).strip(),
            )
            == name
        )


class LazyStart2UseItemUtils(LazyJsonCatalog[Start2UseItemUtils]):
    def __init__(self, json_path: str):
        super().__init__(json_path, Start2UseItemUtils)


start2ConsumeUseUtils = LazyStart2UseItemUtils(
    os.path.join(start2_dir, "api_mst_useitem.json")
)
