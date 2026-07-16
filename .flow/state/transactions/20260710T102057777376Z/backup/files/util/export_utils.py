import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone

from configs.path import get_data_dir, get_db_dir
from service.data_package.improvement_record import WeaponItemVO
from util.json_utils import write_json, write_json_lines
from util.logger import simple_logger

DETAIL_FILE_NAME = "improvement-detail.nedb"
LIST_FILE_NAME = "improvement-list.json"
DAY_ORDER = [
    "all",
    "sunday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
]
LEGACY_FILE_NAMES = ["arsenal_all.nedb", "arsenal_weekday.nedb", "items.nedb"]


def get_improvement_db_dir() -> str:
    return get_db_dir("improvement")


def serialize_clean(obj):
    if obj is None:
        return None
    if hasattr(obj, "to_json"):
        return serialize_clean(obj.to_json())
    if is_dataclass(obj):
        return serialize_clean(asdict(obj))
    if isinstance(obj, dict):
        return {key: serialize_clean(value) for key, value in obj.items() if value is not None}
    if isinstance(obj, (list, tuple)):
        return [serialize_clean(value) for value in obj]
    return obj


def export_to_nedb(data_list: list, file_name: str):
    output_file_path = os.path.join(get_improvement_db_dir(), file_name)
    cleaned_list = [serialize_clean(item) for item in data_list]
    cleaned_list = [item for item in cleaned_list if item is not None]
    count = write_json_lines(output_file_path, cleaned_list, mode="w", log=True)
    simple_logger.debug(f"✅ 导出成功！共写入 {count} 条数据")
    simple_logger.debug(f"📍 文件路径: {os.path.abspath(output_file_path)}")


def _append_unique(values: list, value):
    if value not in values:
        values.append(value)


def build_list_projection(data_list: list[WeaponItemVO]) -> list[list[list]]:
    """Build compact [all, Sunday..Saturday] list views.

    Every row is [itemId, assistantTexts]. Empty assistantTexts is meaningful: the
    item is available without a specific support ship on that view day. Source
    order is preserved even when one Wiki rule is split into multiple recipe routes.
    """
    views: list[list[list]] = [[] for _ in DAY_ORDER]

    for item in data_list:
        entries_by_view: list[list[tuple[int, int, str]]] = [[] for _ in DAY_ORDER]
        available_by_view = [False for _ in DAY_ORDER]
        sequence = 0

        for improvement in item.improvement_list:
            for ship_week in improvement.ship_week_list:
                week = list(ship_week.week or [])
                text = (ship_week.text or "").strip()
                enabled_days = [day for day in range(7) if day < len(week) and bool(week[day])]
                if not enabled_days:
                    continue

                source_order = getattr(ship_week, "source_order", -1)
                sort_order = source_order if source_order >= 0 else 10 ** 9
                available_by_view[0] = True
                if text:
                    entries_by_view[0].append((sort_order, sequence, text))
                sequence += 1

                for day in enabled_days:
                    view_index = day + 1
                    available_by_view[view_index] = True
                    if text:
                        entries_by_view[view_index].append((sort_order, sequence, text))
                    sequence += 1

        for view_index in range(len(DAY_ORDER)):
            if not available_by_view[view_index]:
                continue
            ordered_texts = []
            for _, _, text in sorted(entries_by_view[view_index]):
                _append_unique(ordered_texts, text)
            views[view_index].append([item.id, ordered_texts])

    return views


def _read_start2_version() -> str:
    version_path = os.path.join(get_data_dir("start2_data"), "current_version.txt")
    if not os.path.exists(version_path):
        return "unknown"
    with open(version_path, "r", encoding="utf-8") as file:
        return file.read().strip() or "unknown"


def export_list_data(data_list: list[WeaponItemVO]):
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    list_data = {
        "metadata": {
            "schemaVersion": 2,
            "dataVersion": generated_at,
            "generatedAt": generated_at,
            "shipMasterVersion": _read_start2_version(),
            "dayOrder": DAY_ORDER,
            "rowSchema": ["itemId", "assistantTexts"],
            "detailFile": DETAIL_FILE_NAME,
            "itemCount": len(data_list),
        },
        "data": build_list_projection(data_list),
    }
    write_json(
        os.path.join(get_improvement_db_dir(), LIST_FILE_NAME),
        list_data,
        mode="w",
        log=True,
    )


def export_data(data_list: list[WeaponItemVO]):
    """Export the two public projections consumed by the plugin."""
    export_to_nedb(data_list, file_name=DETAIL_FILE_NAME)
    export_list_data(data_list)


def clear():
    for file_name in LEGACY_FILE_NAMES + [DETAIL_FILE_NAME, LIST_FILE_NAME]:
        file_path = os.path.join(get_improvement_db_dir(), file_name)
        if os.path.exists(file_path):
            os.remove(file_path)
