from __future__ import annotations

import copy
import re

from service.improvement.model import ImprovementStage, ImprovementStageAlternative
from service.akashi_list.akashi_list_utils import (
    extract_name_and_count,
    extract_weapon_name,
    query_consumable,
    require_record,
)
from util.logger import simple_logger

def copy_stage_recipe(stage: ImprovementStage):
    copied = copy.deepcopy(stage)
    copied.route_alternatives = []
    return copied

def parse_stage_consumable(container_node):
    title_nodes = container_node.xpath(".//*[@title] | self::*[@title]")
    if not title_nodes:
        raise ValueError("assistant-specific stage recipe has no titled consumable")
    title_node = title_nodes[0]
    title = title_node.get("title") or ""
    item_name = extract_weapon_name(title)
    text = " ".join(container_node.xpath("string(.)").split())
    parsed_name, count = extract_name_and_count(text)
    if parsed_name:
        item_name = parsed_name
    consumable = query_consumable(item_name)
    consumable = require_record(consumable, "assistant-specific consumable", item_name)
    consumable.count = count
    return consumable

def parse_stage_route_alternatives(resource_node, base_stage: ImprovementStage, ship_name_resolver):
    for condition_node in resource_node.xpath("./div[contains(concat(' ', normalize-space(@class), ' '), ' sub ')]"):
        raw_condition = " ".join(condition_node.xpath("string(.)").split())
        match = re.search(r"二番艦[：:]\s*(.+?)\s*限定$", raw_condition)
        if not match:
            simple_logger.warning(f"[route] unrecognized assistant condition: {raw_condition}")
            continue
        condition_text = match.group(1).strip()
        resolution = ship_name_resolver.resolve(condition_text)
        condition_ship_ids = list(resolution.anchor_ship_ids or resolution.ship_ids)
        if not condition_ship_ids:
            simple_logger.warning(f"[route] assistant condition resolved empty: {condition_text}")
            continue

        alternative_nodes = condition_node.xpath("following-sibling::*[1]")
        if not alternative_nodes:
            simple_logger.warning(f"[route] assistant condition has no alternate recipe: {condition_text}")
            continue

        alternative_stage = copy_stage_recipe(base_stage)
        alternative_stage.consumable_list = [
            parse_stage_consumable(alternative_nodes[0])
        ]
        base_stage.route_alternatives.append(ImprovementStageAlternative(
            condition_text=condition_text,
            # `限定` is an exact selector. Do not forward-expand it to future
            # remodels merely because normal Wiki helper names use inheritance.
            ship_id_list=condition_ship_ids,
            stage=alternative_stage,
        ))
