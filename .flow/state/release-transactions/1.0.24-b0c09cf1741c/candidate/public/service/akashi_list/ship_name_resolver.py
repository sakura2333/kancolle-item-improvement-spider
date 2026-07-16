from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from util.start2.start2_ship_utils import Start2ShipUtils
from util.text_utils import normalize_name


SHIP_NAME_ALIASES = {
    normalize_name("C.d.C nuovo"): "Conte di Cavour nuovo",
    normalize_name("Gambier BayMk.II"): "Gambier Bay Mk.II",
}

GRAMMAR_SUFFIXES = ("不可", "可", "のみ")
SEPARATOR_PATTERN = re.compile(r"[/・]")
IMAGE_SORTNO_PATTERN = re.compile(r"/s?(\d+)([a-z]?)\.[^/]+$", re.IGNORECASE)


@dataclass
class ShipNameResolution:
    raw_text: str
    ship_ids: List[int] = field(default_factory=list)
    anchor_ship_ids: List[int] = field(default_factory=list)
    match_distance_by_id: Dict[int, int] = field(default_factory=dict)
    status: str = "resolved"
    warnings: List[str] = field(default_factory=list)


class ShipNameResolver:
    """Compile Akashi List's compact ship expressions into concrete ship IDs.

    The resolver deliberately owns only the Wiki naming language. Cross-rule weekday
    precedence is calculated separately after every rule in an improvement route has
    been resolved.
    """

    def __init__(self, ship_utils: Start2ShipUtils):
        self.ship_utils = ship_utils
        self.ships = list(ship_utils.ships)
        self.by_id = {int(ship["api_id"]): ship for ship in self.ships if ship.get("api_id")}
        self.name_index: Dict[str, List[dict]] = {}
        self.next_id: Dict[int, int] = {}
        self.undirected: Dict[int, set[int]] = {}
        self._family_cache: Dict[int, List[int]] = {}
        self._cycle_cache: Dict[int, Optional[List[int]]] = {}

        for ship in self.ships:
            ship_id = int(ship.get("api_id") or 0)
            if not ship_id:
                continue
            key = normalize_name(ship.get("api_name") or "")
            if key:
                self.name_index.setdefault(key, []).append(ship)

            after_id = self._as_positive_int(ship.get("api_aftershipid"))
            self.next_id[ship_id] = after_id
            self.undirected.setdefault(ship_id, set())
            if after_id and after_id in self.by_id:
                self.undirected.setdefault(after_id, set())
                self.undirected[ship_id].add(after_id)
                self.undirected[after_id].add(ship_id)

    @staticmethod
    def _as_positive_int(value) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return parsed if parsed > 0 else 0

    @staticmethod
    def _dedupe(values: Iterable[int]) -> List[int]:
        result: List[int] = []
        seen = set()
        for value in values:
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    def _find_cycle(self, ship_id: int) -> Optional[List[int]]:
        if ship_id in self._cycle_cache:
            return self._cycle_cache[ship_id]

        path: List[int] = []
        positions: Dict[int, int] = {}
        current = ship_id
        while current and current in self.by_id and current not in positions:
            if current in self._cycle_cache:
                cycle = self._cycle_cache[current]
                for visited in path:
                    self._cycle_cache[visited] = cycle if cycle and visited in cycle else None
                return cycle if cycle and ship_id in cycle else None
            positions[current] = len(path)
            path.append(current)
            current = self.next_id.get(current, 0)

        cycle: Optional[List[int]] = None
        if current in positions:
            cycle = path[positions[current]:]
            cycle = sorted(
                cycle,
                key=lambda sid: (
                    int(self.by_id[sid].get("api_sortno") or 10 ** 9),
                    sid,
                ),
            )

        for visited in path:
            self._cycle_cache[visited] = cycle if cycle and visited in cycle else None
        return cycle if cycle and ship_id in cycle else None

    def forward_closure(self, ship_id: int) -> List[int]:
        result: List[int] = []
        visited = set()
        current = ship_id

        while current and current in self.by_id and current not in visited:
            cycle = self._find_cycle(current)
            if cycle:
                start = cycle.index(current)
                result.extend(cycle[start:])
                break

            result.append(current)
            visited.add(current)
            current = self.next_id.get(current, 0)

        return self._dedupe(result)

    def family_ids(self, ship_id: int) -> List[int]:
        if ship_id in self._family_cache:
            return self._family_cache[ship_id]

        result: List[int] = []
        stack = [ship_id]
        visited = set()
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            if current in self.by_id:
                result.append(current)
                stack.extend(self.undirected.get(current, ()))

        result.sort(key=lambda sid: (
            int(self.by_id[sid].get("api_sortno") or 10 ** 9),
            sid,
        ))
        for member in result:
            self._family_cache[member] = result
        return result

    def _ship_name(self, ship_id: int) -> str:
        return str(self.by_id[ship_id].get("api_name") or "")

    def _image_anchor(self, image_src: Optional[str]) -> Optional[int]:
        if not image_src:
            return None
        match = IMAGE_SORTNO_PATTERN.search(image_src)
        if not match:
            return None
        sortno = int(match.group(1))
        ship = self.ship_utils.get_by_sortno(sortno)
        return int(ship["api_id"]) if ship else None

    def _exact_matches(self, text: str) -> List[int]:
        normalized = normalize_name(text)
        alias = SHIP_NAME_ALIASES.get(normalized)
        if alias:
            normalized = normalize_name(alias)
        return [int(ship["api_id"]) for ship in self.name_index.get(normalized, [])]

    def _choose_exact(
        self,
        text: str,
        image_anchor_id: Optional[int] = None,
        fallback_anchor_id: Optional[int] = None,
    ) -> Optional[int]:
        matches = self._exact_matches(text)
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        if image_anchor_id in matches:
            return image_anchor_id
        if fallback_anchor_id in matches:
            return fallback_anchor_id
        return sorted(matches, key=lambda sid: (
            int(self.by_id[sid].get("api_sortno") or 10 ** 9), sid
        ))[0]

    def _resolve_fragment(self, fragment: str, anchor_id: int) -> int:
        fragment = fragment.strip(" ,，")
        exact = self._choose_exact(fragment, fallback_anchor_id=anchor_id)
        if exact:
            return exact

        family = self.family_ids(anchor_id)
        family_names = [(sid, self._ship_name(sid)) for sid in family]
        root_id = min(family, key=lambda sid: (len(normalize_name(self._ship_name(sid))), sid))
        root_name = self._ship_name(root_id)
        anchor_name = self._ship_name(anchor_id)

        generated = [
            f"{root_name}{fragment}",
            f"{anchor_name}{fragment}",
        ]
        for candidate_text in generated:
            candidate = self._choose_exact(candidate_text, fallback_anchor_id=anchor_id)
            if candidate and candidate in family:
                return candidate

        normalized_fragment = normalize_name(fragment)
        scored: List[Tuple[int, int]] = []
        for sid, name in family_names:
            normalized_name = normalize_name(name)
            score = 0
            if normalized_name.endswith(normalized_fragment):
                score = 80
            elif normalized_fragment and normalized_fragment in normalized_name:
                score = 60
            if score:
                common_prefix = 0
                for left, right in zip(normalize_name(anchor_name), normalized_name):
                    if left != right:
                        break
                    common_prefix += 1
                scored.append((score + common_prefix, sid))

        if not scored:
            raise ValueError(f"cannot resolve ship fragment '{fragment}' from '{anchor_name}'")
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        best_score = scored[0][0]
        best = [sid for score, sid in scored if score == best_score]
        if len(best) != 1:
            names = [self._ship_name(sid) for sid in best]
            raise ValueError(f"ambiguous ship fragment '{fragment}' from '{anchor_name}': {names}")
        return best[0]

    @staticmethod
    def _split_grammar_parenthesis(raw_text: str) -> Tuple[str, Optional[str]]:
        match = re.match(r"^(.*)\(([^()]*)\)$", raw_text)
        if not match:
            return raw_text, None
        main, modifier = match.groups()
        if modifier.endswith(GRAMMAR_SUFFIXES):
            return main, modifier
        return raw_text, None

    def _resolve_main_anchors(
        self,
        main_text: str,
        image_anchor_id: Optional[int],
        fallback_anchor_id: Optional[int],
    ) -> List[int]:
        parts = [part.strip() for part in SEPARATOR_PATTERN.split(main_text) if part.strip()]
        if not parts:
            return []

        first = self._choose_exact(parts[0], image_anchor_id, fallback_anchor_id)
        if first is None:
            # Image is a useful final fallback for malformed/aliased Wiki labels.
            first = image_anchor_id or fallback_anchor_id
        if first is None:
            raise ValueError(f"cannot resolve ship name '{parts[0]}'")

        anchors = [first]
        for fragment in parts[1:]:
            anchors.append(self._resolve_fragment(fragment, first))
        return self._dedupe(anchors)

    def _modifier_fragments(self, modifier_body: str) -> List[str]:
        return [part.strip() for part in re.split(r"[/,，・]", modifier_body) if part.strip()]

    def resolve(
        self,
        raw_text: str,
        image_src: Optional[str] = None,
        fallback_anchor_id: Optional[int] = None,
    ) -> ShipNameResolution:
        raw_text = (raw_text or "").strip()
        if raw_text in ("", "-"):
            return ShipNameResolution(raw_text=raw_text)

        image_anchor_id = self._image_anchor(image_src)

        # Official names may themselves contain parentheses, e.g. 吹雪改三護(六式).
        exact_full = self._choose_exact(raw_text, image_anchor_id, fallback_anchor_id)
        if exact_full is not None:
            ship_ids = self.forward_closure(exact_full)
            return ShipNameResolution(
                raw_text=raw_text,
                ship_ids=ship_ids,
                anchor_ship_ids=[exact_full],
                match_distance_by_id={sid: index for index, sid in enumerate(ship_ids)},
            )

        main_text, modifier = self._split_grammar_parenthesis(raw_text)
        anchors = self._resolve_main_anchors(
            main_text,
            image_anchor_id=image_anchor_id,
            fallback_anchor_id=fallback_anchor_id,
        )

        if modifier and modifier.endswith("のみ"):
            # The current corpus uses this to disambiguate duplicate-name forms.
            only_anchor = image_anchor_id or anchors[0]
            return ShipNameResolution(
                raw_text=raw_text,
                ship_ids=[only_anchor],
                anchor_ship_ids=[only_anchor],
                match_distance_by_id={only_anchor: 0},
            )

        ordered_ids: List[int] = []
        distance_by_id: Dict[int, int] = {}
        for anchor in anchors:
            closure = self.forward_closure(anchor)
            for distance, ship_id in enumerate(closure):
                if ship_id not in ordered_ids:
                    ordered_ids.append(ship_id)
                distance_by_id[ship_id] = min(distance_by_id.get(ship_id, 10 ** 9), distance)

        if modifier and modifier.endswith("不可"):
            body = modifier[:-2].strip()
            range_exclusion = body.endswith("～") or body.endswith("~")
            if range_exclusion:
                body = body[:-1].strip()
            exclusions: List[int] = []
            for fragment in self._modifier_fragments(body):
                excluded_anchor = self._resolve_fragment(fragment, anchors[0])
                if range_exclusion:
                    exclusions.extend(self.forward_closure(excluded_anchor))
                else:
                    exclusions.append(excluded_anchor)
            excluded = set(exclusions)
            ordered_ids = [ship_id for ship_id in ordered_ids if ship_id not in excluded]
            distance_by_id = {
                ship_id: distance for ship_id, distance in distance_by_id.items()
                if ship_id not in excluded
            }

        # "可" is explanatory in the source syntax. The default forward closure
        # already includes the named successor forms, so no extra mutation is needed.
        return ShipNameResolution(
            raw_text=raw_text,
            ship_ids=ordered_ids,
            anchor_ship_ids=anchors,
            match_distance_by_id=distance_by_id,
        )


def resolve_all_ship_names(
    resolver: ShipNameResolver,
    records: Sequence[Tuple[str, Optional[str], Optional[int]]],
) -> List[ShipNameResolution]:
    return [
        resolver.resolve(text, image_src=image_src, fallback_anchor_id=anchor_id)
        for text, image_src, anchor_id in records
    ]
