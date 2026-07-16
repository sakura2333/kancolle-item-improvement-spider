from __future__ import annotations

from pathlib import Path

from .common import QualityGateError, _non_empty_string, _positive_int, _read_nedb

def _validate_drop_from(path: Path) -> tuple[int, int]:
    records = _read_nedb(path)
    ids: set[int] = set()
    relation_count = 0
    for index, record in enumerate(records):
        item_id = record.get("equipmentId")
        if not _positive_int(item_id) or item_id in ids:
            raise QualityGateError(f"invalid or duplicate drop-from equipment id at record {index}")
        if not _non_empty_string(record.get("equipmentName")):
            raise QualityGateError(f"drop-from equipment {item_id} has no name")
        sources = record.get("sources")
        if not isinstance(sources, list) or not sources:
            raise QualityGateError(f"drop-from equipment {item_id} has no sources")
        for source_index, source in enumerate(sources):
            if not isinstance(source, dict):
                raise QualityGateError(f"drop-from equipment {item_id} source {source_index} is not an object")
            if not _positive_int(source.get("shipId")) or not _non_empty_string(source.get("shipName")):
                raise QualityGateError(f"drop-from equipment {item_id} source {source_index} has invalid ship")
            if source.get("method") not in {"initial", "remodel"}:
                raise QualityGateError(f"drop-from equipment {item_id} source {source_index} has invalid method")
            if not _positive_int(source.get("quantity")):
                raise QualityGateError(f"drop-from equipment {item_id} source {source_index} has invalid quantity")
            relation_count += int(source["quantity"])
        ids.add(item_id)
    return len(records), relation_count


def _validate_equipment_sources(path: Path) -> tuple[int, int, int, int]:
    records = _read_nedb(path)
    ids: set[int] = set()
    ship_relations = 0
    upgrade_relations = 0
    quest_relations = 0
    for index, record in enumerate(records):
        equipment_id = record.get("equipmentId")
        if not _positive_int(equipment_id) or equipment_id in ids:
            raise QualityGateError(
                f"invalid or duplicate equipment-source id at record {index}"
            )
        if not _non_empty_string(record.get("equipmentName")):
            raise QualityGateError(f"equipment-source {equipment_id} has no name")
        source = record.get("source")
        if not isinstance(source, dict) or set(source) != {
            "shipIds", "upgradeFromItemIds", "questKey"
        }:
            raise QualityGateError(
                f"equipment-source {equipment_id} has an invalid source contract"
            )
        for field in ("shipIds", "upgradeFromItemIds", "questKey"):
            values = source.get(field)
            if (
                not isinstance(values, list)
                or any(not _positive_int(value) for value in values)
                or values != sorted(set(values))
            ):
                raise QualityGateError(
                    f"equipment-source {equipment_id} has invalid {field}"
                )
        ship_relations += len(source["shipIds"])
        upgrade_relations += len(source["upgradeFromItemIds"])
        quest_relations += len(source["questKey"])
        ids.add(equipment_id)
    return len(records), ship_relations, upgrade_relations, quest_relations

def _validate_special_bonuses(path: Path) -> tuple[int, int, int, int]:
    records = _read_nedb(path)
    equipment_ids: set[int] = set()
    equipment_type_keys: set[tuple[int, ...]] = set()
    equipment_record_count = 0
    equipment_type_record_count = 0
    rule_count = 0
    for index, record in enumerate(records):
        target = record.get("target")
        if not isinstance(target, dict):
            raise QualityGateError(f"special-bonus record {index} has no target")
        target_kind = target.get("kind")
        if target_kind == "equipment":
            item_id = record.get("equipmentId")
            target_ids = target.get("equipmentIds")
            if not _positive_int(item_id) or target_ids != [item_id] or item_id in equipment_ids:
                raise QualityGateError(f"invalid or duplicate special-bonus equipment id at record {index}")
            if not _non_empty_string(record.get("equipmentName")):
                raise QualityGateError(f"special-bonus equipment {item_id} has no name")
            equipment_ids.add(item_id)
            target_label = f"equipment {item_id}"
            equipment_record_count += 1
        elif target_kind == "equipment-type":
            type_ids = record.get("equipmentTypeIds")
            target_ids = target.get("equipmentTypeIds")
            if (
                not isinstance(type_ids, list)
                or not type_ids
                or any(not _positive_int(value) for value in type_ids)
                or target_ids != type_ids
            ):
                raise QualityGateError(f"invalid special-bonus equipment-type target at record {index}")
            key = tuple(type_ids)
            if key in equipment_type_keys:
                raise QualityGateError(f"duplicate special-bonus equipment-type target {list(key)}")
            equipment_type_keys.add(key)
            target_label = f"equipment types {list(key)}"
            equipment_type_record_count += 1
        else:
            raise QualityGateError(f"special-bonus record {index} has unsupported target kind {target_kind!r}")

        rules = record.get("rules")
        if not isinstance(rules, list) or not rules:
            raise QualityGateError(f"special-bonus {target_label} has no rules")
        for rule_index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                raise QualityGateError(f"special-bonus {target_label} rule {rule_index} is not an object")
            bonus = rule.get("bonus")
            if not isinstance(bonus, dict) or not bonus:
                unsupported = rule.get("sourceBonusFields")
                if isinstance(unsupported, dict) and unsupported:
                    fields = ", ".join(sorted(str(key) for key in unsupported))
                    raise QualityGateError(
                        f"special-bonus {target_label} rule {rule_index} has unsupported bonus fields: {fields}"
                    )
                raise QualityGateError(f"special-bonus {target_label} rule {rule_index} has no bonus")
            unsupported = rule.get("sourceBonusFields")
            if isinstance(unsupported, dict) and unsupported:
                fields = ", ".join(sorted(str(key) for key in unsupported))
                raise QualityGateError(
                    f"special-bonus {target_label} rule {rule_index} has unsupported bonus fields: {fields}"
                )
            if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in bonus.values()):
                raise QualityGateError(
                    f"special-bonus {target_label} rule {rule_index} has non-numeric bonus values"
                )
            if not isinstance(rule.get("conditions"), dict):
                raise QualityGateError(f"special-bonus {target_label} rule {rule_index} has invalid conditions")
            rule_count += 1
    return len(records), equipment_record_count, equipment_type_record_count, rule_count
