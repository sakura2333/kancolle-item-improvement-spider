# Improvement data schema v4

The spider publishes two projections under `data/improvement/`.

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

## Diagnostic source data

`data/sources/` is not part of the plugin contract. Each source stores:

- `schedules.nedb`: compatibility name for normalized facts.
- `normalized-facts.nedb`: full route-aware facts.
- `parsed-rules.nedb`: evidence-bearing parsed rows.
- `issues.nedb`: unresolved names and parser problems.
- `metadata.json`: source health and counts.

A fact is identified at full precision by:

`itemId + shipId + capability + updateTargetItemId + routeSignature`

The AI review bundle under `data/sources/ai-review/` contains the prompt, complete
review input, route variants and conflicts. AI output is advisory and never mutates
public data automatically.

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

The package manifest lists `requiredIds`, `availableIds`, and `missingIds` for `assets/useitems`. Required IDs are derived from type-1 consumables referenced by `improvement/detail.nedb`. Publication requires `missingIds` to be empty.
