import re

import mojimoji


def normalize_name(name: str) -> str:
    if not name:
        return ""

    name = str(name)
    name = mojimoji.zen_to_han(name, kana=True)
    name = name.replace("*", "")
    name = name.lower()
    name = re.sub(r"\s+", "", name)
    name = re.sub(r"\?", "", name)
    return name.strip()
