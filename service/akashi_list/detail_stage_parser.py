from __future__ import annotations

import copy
import re
from typing import Dict

from pojo.improvement import ConsumeItem, ImprovementStage
from service.akashi_list.akashi_list_utils import (
    extract_name_and_count,
    extract_weapon_name,
    query_consumable,
    require_record,
    search_title,
)
from service.akashi_list.detail_recipe_parser import parse_stage_route_alternatives
from util.cache import download_pic
from util.html_table_utils import next_td, next_tr
from util.logger import simple_logger
from util.lxml_utils import node_to_string
from util.start2.start2_item_utils import start2ItemUtils
from util.start2.start2_use_item_utils import start2ConsumeUseUtils
from util.text_utils import normalize_name

stage_zero = "0 ～ 5"
stage_six = "6 ～ 9"
stage_max = "MAX"
state_dic: Dict[str, tuple[int, int]] = {
    stage_zero: (0, 5),
    stage_six: (6, 9),
    stage_max: (10, 10),
}


def _download_useitem_image(consumable: ConsumeItem, png_url: str) -> None:
    if int(consumable.type) != 1:
        return
    download_pic(url=png_url, save_path=f"cache/images/{consumable.id}.png")


def process_stage(processor, current_node):
    star_range = [-1,-1]
    improvement_stage_template :ImprovementStage = ImprovementStage()
    stage = ImprovementStage()

    # 取出th
    # <th class=border-right rowspan=2>MAX</th>
    #   processor.stage_zero = '0 ～ 5'
    #   processor.stage_six = '6 ～ 9'
    current_node = current_node.xpath("./th")[0]
    stage_html_text = current_node.text
    has_multi_row = current_node.get("rowspan") is not None

    current_node,_ = next_td(current_node)
    stage.dev_normal, stage.dev_certain = tuple(map(int, re.findall(r"\d+", current_node.text)))
    current_node,_ = next_td(current_node)
    stage.rev_normal, stage.rev_certain = tuple(map(int, re.findall(r"\d+", current_node.text)))
    current_node, _ = next_td(current_node)

    def create_stage_text(_range):
        assert _range [0] >=0 and _range [1] >=_range[0]
        if _range[0] == _range[1]:
            return f'★{_range[0]}'
        else:
            return f'★{_range[0]}~★{_range[1]}'

    #解析消耗的武器
    # consumable_weapon = current_node.xpath(".//*[@title]")[0]
    # if (len(consumable_weapon_nodes) > 0):
    #     consumable_weapon = consumable_weapon_nodes[0]
    # else:
    #     consumable_weapon = current_node.xpath("./a[@data-wid]/div")[0]
    consumable_weapon_text =  current_node.xpath('string(.)')
    if ('-' !=  consumable_weapon_text):

        consumable_weapon_name, count_str = extract_name_and_count(text=consumable_weapon_text)
        consumable_weapon_record = start2ItemUtils.find_by_name_normalized(normalize_name(consumable_weapon_name))
        consumable_weapon_record = require_record(consumable_weapon_record, "consumable weapon", consumable_weapon_name)
        stage.consumable_list.append(ConsumeItem(
            id=consumable_weapon_record.get("api_id"),
            count=int(count_str),
            type=0
        ))

    if stage_html_text == stage_zero:
        star_range=(0,5)
    if stage_html_text == stage_six:
        star_range=(6,9)
    stage.stage_text = create_stage_text(star_range)
    parse_stage_route_alternatives(current_node, stage, processor.ship_name_resolver)

    if has_multi_row:
        def copy_stage(stage_src,stage_dst):
            stage_dst.dev_normal = stage_src.dev_normal
            stage_dst.dev_certain = stage_src.dev_certain
            stage_dst.rev_normal = stage_src.rev_normal
            stage_dst.rev_certain = stage_src.rev_certain
            stage_dst.target_weapon = copy.deepcopy(stage_src.target_weapon)
            stage_dst.consumable_list = copy.deepcopy(stage_src.consumable_list)
            stage_dst.route_alternatives = copy.deepcopy(stage_src.route_alternatives)

        current_node = current_node.getparent().xpath("following-sibling::tr[1]")[0]
        span_list = current_node.xpath(".//span[not(@class)]")
        assert len(span_list) > 0
        copy_stage(stage_src=stage, stage_dst=improvement_stage_template)

        special_levels = [
            int(re.match(r".*?(\d+)", span.xpath("string(.)").strip()).groups()[0])
            for span in span_list
        ]
        first_special_level = min(special_levels)
        if star_range[0] < first_special_level:
            for level in range(star_range[0], first_special_level):
                stage = ImprovementStage()
                copy_stage(stage_src=improvement_stage_template, stage_dst=stage)
                stage.stage_text = create_stage_text((level, level))
                for improvement in processor.item.improvement_list:
                    improvement.stage_list.append(stage)

        for span in span_list:
            level = int(re.match(r".*?(\d+)", span.xpath("string(.)").strip()).groups()[0])

            stage = ImprovementStage()
            copy_stage(stage_src=improvement_stage_template, stage_dst=stage)
            stage.stage_text = create_stage_text((level, level))
            consumable_item_node = span.xpath("following-sibling::span[@class='s-gap'][1]/a[@title]")
            if len(consumable_item_node) == 0:
                simple_logger.error(node_to_string(current_node))
                continue
            consumable_item_name = consumable_item_node[0].xpath('./@title')[0]
            count_text = span.xpath("following-sibling::span[@class='s-gap'][1]/a/img")[0].tail
            count_text = re.match(r".*?(\d+)", count_text).groups()[0]
            consumable = query_consumable(extract_weapon_name(consumable_item_name))
            require_record(consumable, "consumable", consumable_item_name)
            consumable.count = int(count_text)

            png_url = (consumable_item_node[0].xpath('.//@data-src') or consumable_item_node[0].xpath('.//@src'))[0]
            _download_useitem_image(consumable, png_url)
            stage.consumable_list.append(consumable)
            for improvement in processor.item.improvement_list:
                improvement.stage_list.append(stage)
    else:
        for improvement in processor.item.improvement_list:
            improvement.stage_list.append(stage)

    current_node , _= next_tr(current_node=current_node)
    return current_node

def process_upgrade(processor, current_node, kind=""):
    improvement = next(improvement for improvement in processor.item.improvement_list if improvement.kind == kind)
    assert improvement is not None
    upgrade = ImprovementStage()
    # 取出th
    # <th class=border-right rowspan=2>MAX</th>
    #   processor.stage_zero = '0 ～ 5'
    #   processor.stage_six = '6 ～ 9'
    current_node = current_node.xpath("./th")[0]
    has_multi_row = current_node.get("rowspan") is not None

    # 没有升级路径
    if not has_multi_row:
        return next_tr(current_node=current_node)[0]
    else:
        current_node, _ = next_td(current_node)
        upgrade.dev_normal, upgrade.dev_certain = tuple(map(int, re.findall(r"\d+", current_node.text)))
        current_node, _ = next_td(current_node)
        upgrade.rev_normal, upgrade.rev_certain = tuple(map(int, re.findall(r"\d+", current_node.text)))
        current_node, _ = next_td(current_node)

        # todo 升级成高星
        # 第一行是升级用的武器材料
        consumable_weapon_title_node = search_title(current_node)
        consumable_weapon_name = extract_weapon_name(consumable_weapon_title_node[0].xpath('.//@title')[0])
        _ , consumable_weapon_count = extract_name_and_count(consumable_weapon_title_node[0].xpath('string(.//following::figcaption[1])'))
        consumable = query_consumable(consumable_weapon_name)
        require_record(consumable, "upgrade consumable", consumable_weapon_name)
        consumable.count = consumable_weapon_count

        upgrade.consumable_list.append(consumable)

        # 后面几行是升级用的item
        consumable_items = current_node.xpath("./div//*[@title]")[1:]
        for consumable_item in consumable_items:
            consumable_item_name = consumable_item.xpath("./@title")[0]
            consumable_item_record = start2ConsumeUseUtils.find_by_name(consumable_item_name)
            consumable_item_record = require_record(consumable_item_record, "upgrade use item", consumable_item_name)
            consumable_item_id = consumable_item_record.get("api_id")
            png_url = consumable_item.xpath('./@src')[0]
            consumable_item_count = int(consumable_item.xpath('following::figcaption[1]')[0].text.split(" ")[-1])
            useitem = ConsumeItem(id=consumable_item_id, count=consumable_item_count, type=1)
            _download_useitem_image(useitem, png_url)
            upgrade.consumable_list.append(useitem)

        current_node, _ = next_tr(current_node)
        upgrade_to_weapon_node = current_node.xpath("./td/div//*[@title]/div")[-1]
        upgrade_to_weapon_node_text = upgrade_to_weapon_node.xpath('string()') if upgrade_to_weapon_node.tail is None else upgrade_to_weapon_node.tail
        upgrade_to_weapon_name,_,upgrade_to_weapon_level = re.match(r"^([^★]+)(\s★)?(\d+)?$",upgrade_to_weapon_node_text ).groups()
        upgrade_to_weapon_record = start2ItemUtils.find_by_name_normalized(normalize_name(upgrade_to_weapon_name))
        upgrade_to_weapon_record = require_record(upgrade_to_weapon_record, "upgrade target weapon", upgrade_to_weapon_name)
        upgrade.target_weapon.id = upgrade_to_weapon_record.get("api_id")
        upgrade.target_weapon.level = 0 if upgrade_to_weapon_level is None else int(upgrade_to_weapon_level)
        upgrade.target_weapon.name = str(
            upgrade_to_weapon_record.get("api_name") or upgrade_to_weapon_name
        )
        improvement.stage_list.append(upgrade)
        return next_tr(current_node=current_node)[0]

def process_resource(processor, current_node):
    current_node,_ = next_tr(current_node)
    resource = []
    for num in current_node.xpath("./td/span/text()"):
        resource.append(int(num))

    for improvement in processor.item.improvement_list:
        improvement.base_resource = resource

    return next_tr(current_node=current_node)[0]
