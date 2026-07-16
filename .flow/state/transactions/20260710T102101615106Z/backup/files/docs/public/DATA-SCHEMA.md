# Improvement data schema v4

The spider publishes two projections under `dist/data-pipeline/improvement/`.

## `improvement-list.json`

A compact read model for the plugin list page. Its public row shape remains unchanged:

```json
{
  "metadata": {
    "schemaVersion": 2,
    "dayOrder": ["all", "sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"],
    "rowSchema": ["itemId", "assistantTexts"],
    "detailFile": "improvement-detail.nedb"
  },
  "data": [
    [[19, ["鳳翔", "鳳翔改二"]]],
    [[19, ["鳳翔", "鳳翔改二"]]]
  ]
}
```

`data[0]` is the all-days view. `data[1]` through `data[7]` are Sunday through Saturday.
Each row is `[itemId, assistantTexts]`. An empty text array is valid and means the
item can be improved without a named support ship.

Route splitting does not change list ordering: source ship-name order is retained.

## `improvement-detail.nedb`

One JSON object per equipment item. Each `improvementList[]` entry is one complete
recipe route. Different costs, consumables, MAX targets or assistant-limited recipes
must remain separate entries.

Schema v4 adds two normalized views needed by “what can I improve today?” consumers:

- `levelExpectations`: exactly 11 rows for ★0 through ★MAX. ★1..★MAX contain
  source-faithful effect cells from Akashi List. Simple numbers also expose `value`;
  conditional or formula-like cells retain only `valueText` and may set
  `conditional=true`. ★0 is the explicit no-improvement baseline.
- `effectSource`: `status=ok` identifies the parsed single-equipment table;
  `status=unavailable` means the source page has no effect table. Missing effects are
  never guessed.

Each route also exposes `stepList`, exactly 11 actions:

- indices/from levels 0..9 describe the next successful improvement, including the
  exact cost recipe, consumables, resulting level, and `effectExpectationLevel`;
- index/from level 10 describes the MAX equipment conversion. `available=false`
  means the item has no MAX upgrade route; otherwise `expectedResult.targetWeapon`
  contains the converted equipment ID, display name, and initial star level.

```json
{
  "levelExpectations": [
    {"level": 0, "label": "★0", "effects": []},
    {"level": 1, "label": "★1", "effects": [
      {"name": "火力", "valueText": "+1.00", "value": 1.0, "sourceRow": 2}
    ]}
  ],
  "improvementList": [{
    "stepList": [
      {
        "fromLevel": 0,
        "action": "improve",
        "available": true,
        "expectedResult": {"kind": "level", "level": 1, "label": "★1"},
        "effectExpectationLevel": 1,
        "industryResource": [1, 3, 1, 2],
        "consumables": [{"id": 19, "count": 1, "type": 0}]
      },
      {
        "fromLevel": 10,
        "action": "upgrade",
        "available": true,
        "expectedResult": {"kind": "weapon", "targetWeapon": {"id": 228, "name": "12cm単装砲改二", "level": 0}}
      }
    ]
  }]
}
```

Route fields:

- `routeId`: stable recipe-route identifier.
- `routeType`: `default` or `assistant-specific`.
- `routeShipIds`: assistants selecting an assistant-specific recipe.
- `routeExcludedShipIds`: assistants removed from the default recipe.
- `routeSourceText`: source condition such as `玉波改二`.

Existing normalized assistant fields remain:

- `shipWeekList[].shipIdList`: Wiki selector expanded to concrete ship IDs.
- `shipWeekList[].anchorShipIds`: normalized anchors.
- `shipWeekList[].parseStatus`: resolution status.
- `assistantShipIdsByDay`: index 0 is all; indices 1..7 are Sunday..Saturday.
  Each entry is `null` when the route is unavailable, `[]` when available without a
  named assistant, or `[id, ...]` when assistants are required.

Example: `12.7cm連装砲D型改二` has a normal route and a `玉波改二` route. The latter
uses `12.7cm連装高角砲 × 3` at ★0~★5 instead of the normal
`10cm連装高角砲 × 2` recipe.

## `poi-plugin-item-improvement2` compatibility distribution

The canonical improvement detail remains schema 4. During Stable main Preview, the project release tool generates a second npm candidate from the same canonical data:

```text
current candidate
  npm version: <packageVersion>
  dist-tag: latest
  improvement/detail.nedb: schema 4

improvement2 candidate
  npm version: <packageVersion>-improvement2
  dist-tag: improvement2
  improvement/detail.nedb: schema 3
```

The schema-3 detail is an explicit whitelist VO projection. It writes only the original schema-3 fields and naturally ignores all future canonical additions. The schema-2 list is copied byte-for-byte. The compatibility package keeps the normal public paths, so `poi-plugin-item-improvement2` does not need a path adaptation.

The internal generated projection is stored under `packages/kancolle-data/compat/poi-plugin-item-improvement2/` only as release input and quality evidence. It is not exported by the `latest` tarball. Stable Preview freezes both tarballs, versions, hashes, and required dist-tags; Stable release publishes public main, then waits for manual npm authentication and verifies the exact tarballs and tags on rerun.

## Unified equipment sources schema v1

`packages/kancolle-data/equipment/sources.nedb` contains one record for every player equipment in Start2. All three arrays are required even when empty:

```json
{
  "equipmentId": 228,
  "equipmentName": "九六式艦戦改",
  "source": {
    "shipIds": [],
    "upgradeFromItemIds": [19],
    "questKey": []
  }
}
```

- `shipIds`: trusted KcWiki `_api_id` values, accepted only after Start2 ID and Japanese-name consistency checks. WikiWiki card numbers, URL numbers and image filenames are never game IDs.
- `upgradeFromItemIds`: upstream equipment IDs reverse-projected directly from canonical `improvement/detail.nedb`; no name join is performed.
- `questKey`: numeric top-level keys from `kcwikizh/kcQuests/quests-scn.json`. Quest code and name are matching and diagnostic evidence only.

The source-side projection under `dist/data-pipeline/sources/equipment-sources/` stores input hashes and added/changed/removed deltas. It is generated state and is not part of code update identity.

## Diagnostic source data

`dist/data-pipeline/sources/` is not part of the plugin contract. Each source stores:

- `schedules.nedb`: compatibility name for normalized facts.
- `normalized-facts.nedb`: full route-aware facts.
- `parsed-rules.nedb`: evidence-bearing parsed rows.
- `issues.nedb`: unresolved names and parser problems.
- `metadata.json`: source health and counts, including semantic alias hits and unresolved counts.

### WikiWiki equipment acquisition diagnostic

`dist/data-pipeline/sources/wikiwiki-equipment-detail/` is an offline diagnostic dataset generated from browser-session captures registered in `.flow/local/source-cache/_meta.json`; parsing performs no network I/O. A maintainer checkout with Raw Cache rebuilds this dataset; a clean public `main` checkout validates and reuses the published snapshot because original HTML evidence is intentionally not published. `acquisition-records.nedb` stores the Start2 equipment ID, validated page ID, source URL, evidence methods, availability classification, raw text, links, coverage status and acceptance flag. Ship evidence is resolved against Start2. Quest evidence uses `kcwikizh/kcQuests`; `questReferences[]` carries canonical numeric `questKey`, code, name and resolution status, while code and name remain matching evidence only. Accepted numeric keys are projected into the public unified source record. `reference-issues.nedb`, `dataset-issues.nedb` and `unclassified-evidence.nedb` preserve ambiguous, unresolved, unavailable and unsafe-to-normalize evidence.

`configs/wikiwiki-acquisition-replacements.json` is a source-scoped parser dictionary for human-accepted exact headings, explicit context labels, literal classification aliases, classification-only blacklists, historical markers and ignored non-evidence text. Blacklist and alias replacements affect only the classification view and never rewrite captured HTML or emitted `rawText`; unmatched or unsafe evidence remains in `unclassified-evidence.nedb`. Ship reference diagnostics are created only for concrete extracted names, not for generic prose such as “initial equipment of many carriers”.

`configs/wikiwiki-page-name-aliases.json` is a separately reviewed one-way join dictionary from Start2 equipment names to Wiki-authored page names. It is consulted only after exact and conservative normalized-name matching fail; it does not modify canonical names or use Wiki card numbers as IDs.

`configs/source-semantic-aliases.json` is a source-scoped parsing asset, not a consumer schema. Entries are accepted only after human review and are revalidated against current Start2 IDs and names. Strict runs reject any remaining unresolved item or ship name.

A fact is identified at full precision by:

`itemId + shipId + capability + updateTargetItemId + routeSignature`

The AI review bundle under `dist/data-pipeline/sources/ai-review/` contains the prompt, complete
review input, route variants and conflicts. AI output is advisory and never mutates
public data automatically.

### Source history and reliability

`dist/data-pipeline/sources/history/baseline/*.json` is the one-time full stock created when the feature is introduced. `current/*.json` stores the latest successful semantic snapshot, while `changes/*.nedb` appends only `added`, `removed`, `modified`, and `reappeared` events. Failed or partial source results are not observed.

History uses the broad comparison identity:

`itemId + shipId + capability + updateTargetItemId`

`dist/data-pipeline/sources/reliability/summary.json` exposes advisory relative weights derived from pairwise agreement, peer consensus, and sufficiently mature historical corroboration. The file explicitly sets `applyToCanonicalElection=false`; it is not a consumer contract and does not change dataset authority.

## Equipment special bonuses schema v2

`equipment/special-bonuses.nedb` contains one record per bonus target. A target is either a concrete equipment ID or one or more equipment-type IDs.

```json
{
  "target": {"kind": "equipment", "equipmentIds": [315]},
  "equipmentId": 315,
  "equipmentName": "SG レーダー(初期型)",
  "rules": [{"bonus": {"range": 1}, "conditions": {}}]
}
```

```json
{
  "target": {"kind": "equipment-type", "equipmentTypeIds": [9]},
  "equipmentTypeIds": [9],
  "rules": [{"bonus": {"firepower": 1}, "conditions": {}}]
}
```

Consumers must branch on `target.kind`; equipment-type rules must not be mistaken for a missing `equipmentId`.

## Use-item icon integrity

The package manifest lists `requiredIds`, `availableIds`, and `missingIds` for `assets/useitem`. Required IDs are derived from type-1 consumables referenced by `improvement/detail.nedb`. Publication requires `missingIds` to be empty.
