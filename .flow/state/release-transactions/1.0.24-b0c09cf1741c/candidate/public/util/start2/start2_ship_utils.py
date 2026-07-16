from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable

from util.start2.catalog import IndexedCatalog, LazyJsonCatalog
from util.start2.config import start2_dir

Ship = dict[str, Any]


class Start2ShipUtils(IndexedCatalog):
    def __init__(self, source: str | Path | Iterable[Ship]):
        if isinstance(source, (str, Path)):
            path = Path(source)
            if path.exists():
                import json

                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, list):
                    raise ValueError(f"start2 ship catalog must be an array: {path}")
                items: Iterable[Ship] = payload
            else:
                from util.logger import simple_logger

                simple_logger.warning(f"[start2] 找不到文件: {path}")
                items = []
        else:
            items = source
        super().__init__(items)
        self.ships = self.items

    def get_by_id(self, ship_id: int) -> Ship | None:
        return self.find_by_id(ship_id)

    def get_by_name(self, name: str) -> Ship | None:
        return super().find_by_name(name)

    def get_by_name_lower(self, name: str) -> Ship | None:
        return super().find_by_name_lower(name)

    def get_by_name_normalized(self, name: str) -> Ship | None:
        return super().find_by_name_normalized(name)

    def get(self, *, api_id=None, api_sortno=None, name=None, lower_name=None) -> Ship | None:
        if api_id is not None:
            return self.get_by_id(api_id)
        if api_sortno is not None:
            return self.get_by_sortno(api_sortno)
        if name is not None:
            return self.get_by_name(name)
        if lower_name is not None:
            return self.get_by_name_lower(lower_name)
        return None

    def parse_ship_id(self, img_src: str, element_text: str) -> int:
        match = re.search(r"/s?([^/\.]+)\.", img_src)
        if not match:
            raise ValueError(f"无法解析图片路径: {img_src}")
        raw_id_part = match.group(1)
        if raw_id_part.isdigit():
            return int(raw_id_part)
        clean_name = element_text.split("(")[0].strip()
        ship = self.get_by_name(clean_name) or self.find_one(
            lambda item: item["api_name"] == clean_name
        )
        if ship:
            return int(ship["api_id"])
        raise ValueError(
            f"无法在 start2 中匹配舰船 ID [Name: {clean_name}, Img: {raw_id_part}]"
        )

    def get_family_chain(self, identifier: int | str) -> list[Ship]:
        current = self.get_by_id(identifier) if isinstance(identifier, int) else self.get_by_name(identifier)
        if not current:
            raise ValueError(f"未找到舰娘: {identifier} , id = {identifier}")
        current_id = current.get("api_id")
        before: list[Ship] = []
        visited_ids = {current_id}
        while True:
            before_record = self.find_one(
                lambda ship: ship.get("api_aftershipid") == current_id
            )
            if not before_record:
                break
            before_id = before_record.get("api_id")
            if before_id in visited_ids:
                break
            before.append(before_record)
            visited_ids.add(before_id)
            current_id = before_id
        family = list(reversed(before))
        family.append(current)
        while True:
            next_id = int(current.get("api_aftershipid", 0))
            if next_id == 0 or next_id in visited_ids:
                break
            next_ship = self.get_by_id(next_id)
            if not next_ship:
                break
            current = next_ship
            family.append(current)
            visited_ids.add(next_id)
        return family


class LazyStart2ShipUtils(LazyJsonCatalog[Start2ShipUtils]):
    def __init__(self, start2_path: str):
        super().__init__(start2_path, Start2ShipUtils, allow_missing=True)
        self.start2_path = start2_path


ship_utils = LazyStart2ShipUtils(os.path.join(start2_dir, "api_mst_ship.json"))
