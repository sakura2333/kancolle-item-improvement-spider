from __future__ import annotations

from lxml import etree

from service.improvement.model import WeaponItem
from service.akashi_list.akashi_list_utils import require_record
from service.akashi_list.daily_ship_parser import process_daily_ships
from service.akashi_list.detail_stage_parser import (
    download_detail_equipment_image,
    process_resource,
    process_stage,
    process_upgrade,
    stage_max,
)
from service.akashi_list.improvement_expectation import parse_level_expectations
from service.akashi_list.ship_name_resolver import ShipNameResolver
from util.html_table_utils import next_tr
from util.start2.start2_item_utils import start2ItemUtils
from util.start2.start2_ship_utils import ship_utils
from util.text_utils import normalize_name


class DetailProcessor:
    """Coordinates item identity, daily assistants and stage parsing.

    HTML recipe parsing lives in focused helper modules; this class only owns
    per-page state and traversal order.
    """

    def __init__(self):
        self.item = WeaponItem()
        self.result: list[WeaponItem] = []
        self.ship_name_resolver = ShipNameResolver(ship_utils.load())

    def process_item(self, page_node) -> None:
        name = page_node.xpath("//div/span[@class='wname']/text()")[0]
        record = start2ItemUtils.find_by_name_normalized(
            name=normalize_name(str(name))
        )
        record = require_record(record, "weapon", str(name))
        self.item.id = record["api_id"]
        self.item.name = record["api_name"]

    def process_kind_title(self, current_node):
        kind = next(
            (
                value
                for value in current_node.xpath("./th/@class")[0].split()
                if value.startswith("kind")
            ),
            "",
        )
        current_node, _ = next_tr(current_node)
        return self.process_upgrade(current_node=current_node, kind=kind)

    def process_stage(self, current_node):
        return process_stage(self, current_node)

    def process_upgrade(self, current_node, kind: str = ""):
        return process_upgrade(self, current_node, kind=kind)

    def process_resource(self, current_node):
        return process_resource(self, current_node)

    def process_tr(self, page_node):
        rows = page_node.xpath("//div[@class='resource-table']/table/tr")[2:]
        current_node = rows[0]
        while current_node is not None:
            if current_node.xpath("./th[@class='border-right']"):
                text = current_node.xpath("./th[@class='border-right']/text()")[0]
                current_node = (
                    self.process_upgrade(current_node)
                    if text == stage_max
                    else self.process_stage(current_node)
                )
            elif current_node.xpath(".//span[@class='remodel-info']"):
                current_node = self.process_kind_title(current_node)
            elif current_node.xpath(".//th[@class='title resource-title']"):
                current_node = self.process_resource(current_node)
        return current_node

    def process_daily_ships(self, page_node) -> None:
        process_daily_ships(self, page_node)

    def clear(self) -> None:
        self.result.append(self.item)
        self.item = WeaponItem()

    def process_detail_page(self, page) -> None:
        page_node = etree.HTML(page)
        self.process_item(page_node)
        self.item.effect_source, self.item.level_expectations = parse_level_expectations(
            page_node
        )
        download_detail_equipment_image(self.item.id, page_node)
        self.process_daily_ships(page_node)
        self.process_tr(page_node)
        self.clear()
