from lxml import etree


def node_to_string(node):
    return etree.tostring(node, encoding="utf-8", method="html").decode("utf-8")
