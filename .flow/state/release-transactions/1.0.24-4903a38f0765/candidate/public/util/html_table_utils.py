from util.logger import simple_logger
from util.lxml_utils import node_to_string


def next_tr(current_node):
    while current_node.tag != "tr":
        current_node = current_node.getparent()

    next_tr_nodes = current_node.xpath("following-sibling::tr[1]")
    if not next_tr_nodes:
        return None, False

    result_node = next_tr_nodes[0]
    simple_logger.debug(f"{node_to_string(result_node)}")
    return result_node, True


def next_td(td_node):
    next_sibling_td = td_node.xpath("following-sibling::td[1]")
    if next_sibling_td:
        result_node = next_sibling_td[0]
        simple_logger.debug(f"{node_to_string(result_node)}")
        return result_node, False

    parent_tr = td_node.getparent()
    if parent_tr is None or parent_tr.tag != "tr":
        return None, False

    next_tr_nodes = parent_tr.xpath("following-sibling::tr[1]")
    if not next_tr_nodes:
        return None, False

    first_td = next_tr_nodes[0].xpath("./td[1]")
    if first_td:
        result_node = first_td[0]
        simple_logger.debug(f"{node_to_string(result_node)}")
        return result_node, True

    return None, True
