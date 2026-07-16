from __future__ import annotations

from pojo.improvement import Improvement, ShipWeek

def process_daily_ships(processor, page_node):
    support_ship_nodes = page_node.xpath(".//div[contains(@class, 'support-ship-table')]//td/div[@class='support-ship']")
    for source_order, support_ship_node in enumerate(support_ship_nodes):
        kind = next(
            (c for c in support_ship_node.xpath('./div/@class')[0].split() if c.startswith("kind"))
            , "")
        improvement = next((k for k in processor.item.improvement_list if k.kind == kind), None)
        if improvement is None:
            improvement = Improvement()
            improvement.kind = kind
            processor.item.improvement_list.append(improvement)

        #把所以text抓出来 最后一个就是船名
        text_list = []
        for temp_node in support_ship_node:
            text_list.append(temp_node.text)
            text_list.append(temp_node.tail)
        ship_name = [t for t in text_list if t][-1].strip()
        image_src_list = support_ship_node.xpath('./img/@data-src | ./img/@src')
        image_src = image_src_list[0] if image_src_list else None
        resolution = processor.ship_name_resolver.resolve(ship_name, image_src=image_src)
        weeks = [
            span.get("class") == "enable"
            for span in support_ship_node.xpath('./div/span')
        ]

        legacy_anchor = resolution.anchor_ship_ids[0] if resolution.anchor_ship_ids else 0
        improvement.ship_week_list.append(ShipWeek(
            id=[legacy_anchor],
            text="" if ship_name == "-" else ship_name,
            week=weeks,
            ship_id_list=resolution.ship_ids,
            anchor_ship_ids=resolution.anchor_ship_ids,
            parse_status=resolution.status,
            parse_warnings=resolution.warnings,
            source_order=source_order,
            match_distance_by_id=resolution.match_distance_by_id,
        ))
    return
