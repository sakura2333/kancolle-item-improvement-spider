from __future__ import annotations

"""Canonical schema versions shared by package production and validation.

Do not duplicate these values in producer/validator Python code. Cross-language
consumer checks are covered by project tests so a schema bump cannot leave the
build pipeline internally inconsistent.
"""

DATASET_SCHEMA_VERSIONS: dict[str, int] = {
    "improvement": 4,
    "equipmentDropFrom": 1,
    "equipmentSources": 2,
    "equipmentSpecialBonuses": 2,
    "equipmentImages": 2,
    "useitemIcons": 2,
}

IMPROVEMENT_LIST_SCHEMA_VERSION = 2
IMPROVEMENT2_DETAIL_SCHEMA_VERSION = 3
IMPROVEMENT2_LIST_SCHEMA_VERSION = 2
IMPROVEMENT2_USEITEM_ICONS_SCHEMA_VERSION = 1
