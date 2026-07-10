import re

import jaconv


def normalize_name(name: str) -> str:
    if not name:
        return ""

    name = str(name)
    name = jaconv.z2h(name, kana=True, ascii=True, digit=True)
    name = name.replace("*", "")
    name = name.lower()
    name = re.sub(r"\s+", "", name)
    name = re.sub(r"\?", "", name)
    return name.strip()
