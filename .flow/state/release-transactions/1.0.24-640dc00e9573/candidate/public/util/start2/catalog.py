from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Generic, Iterable, TypeVar

from util.logger import simple_logger
from util.text_utils import normalize_name

Item = dict[str, Any]
Predicate = Callable[[Item], bool]
CatalogT = TypeVar("CatalogT")


class IndexedCatalog:
    """Shared indexed view over a start2 JSON collection."""

    def __init__(self, items: Iterable[Item]):
        self.items: list[Item] = list(items)
        self.id_map: dict[int, Item] = {}
        self.name_map: dict[str, Item] = {}
        self.name_lower_map: dict[str, Item] = {}
        self.name_normalized_map: dict[str, Item] = {}
        self.sortno_map: dict[int, Item] = {}
        self._build_index()

    @staticmethod
    def _first(item: Item, *keys: str) -> Any:
        for key in keys:
            value = item.get(key)
            if value is not None:
                return value
        return None

    def _build_index(self) -> None:
        for item in self.items:
            item_id = self._first(item, "api_id", "id")
            name = self._first(item, "api_name", "name")
            sortno = self._first(item, "api_sortno", "sortno")
            if item_id is not None:
                self.id_map[int(item_id)] = item
            if name:
                text = str(name)
                self.name_map[text] = item
                self.name_lower_map[text.lower()] = item
                self.name_normalized_map[normalize_name(text)] = item
            if sortno is not None:
                self.sortno_map[int(sortno)] = item

    def find_one(self, predicate: Predicate) -> Item | None:
        for item in self.items:
            try:
                if predicate(item):
                    return item
            except Exception:
                simple_logger.error(self.items)
        return None

    def find_all(self, predicate: Predicate) -> list[Item]:
        result: list[Item] = []
        for item in self.items:
            try:
                if predicate(item):
                    result.append(item)
            except Exception:
                simple_logger.error(self.items)
        return result

    def find_by_id(self, api_id: int) -> Item | None:
        return self.id_map.get(api_id)

    def find_by_name(self, name: str) -> Item | None:
        return self.name_map.get(name)

    def find_by_name_lower(self, name: str) -> Item | None:
        return self.name_lower_map.get(name.lower())

    def find_by_name_normalized(self, name: str) -> Item | None:
        return self.name_normalized_map.get(name)

    def find_contains_name(self, keyword: str) -> list[Item]:
        return self.find_all(lambda item: keyword in str(item.get("api_name", "")))

    def find_by_type(self, type_idx: int, value: int) -> list[Item]:
        return self.find_all(
            lambda item: len(item.get("api_type", [])) > type_idx
            and item["api_type"][type_idx] == value
        )

    def get_by_sortno(self, sortno: int) -> Item | None:
        return self.sortno_map.get(sortno)

    def build_name_index(self) -> dict[str, Item]:
        return dict(self.name_map)


class LazyJsonCatalog(Generic[CatalogT]):
    """Lazy, reloadable JSON catalog used by all start2 readers."""

    def __init__(
        self,
        json_path: str | Path,
        factory: Callable[[Iterable[Item]], CatalogT],
        *,
        allow_missing: bool = False,
    ):
        self.json_path = Path(json_path)
        self._factory = factory
        self._allow_missing = allow_missing
        self._instance: CatalogT | None = None

    def load(self) -> CatalogT:
        if self._instance is None:
            if not self.json_path.exists():
                if not self._allow_missing:
                    raise FileNotFoundError(self.json_path)
                simple_logger.warning(f"[start2] 找不到文件: {self.json_path}")
                values: Iterable[Item] = []
            else:
                payload = json.loads(self.json_path.read_text(encoding="utf-8"))
                if not isinstance(payload, list):
                    raise ValueError(f"start2 catalog must be an array: {self.json_path}")
                values = payload
            self._instance = self._factory(values)
        return self._instance

    def reload(self) -> None:
        self._instance = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.load(), name)
