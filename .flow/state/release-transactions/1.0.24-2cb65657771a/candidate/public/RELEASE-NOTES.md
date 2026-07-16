# Release Notes

## 1.0.24 (2026-07-15)

本页由发布候选生成器汇总数据包 Changelog、机器发布记录和本次 Git 变更后生成。只保留面向使用者和数据消费方的摘要。

### 新增

- Added required non-null `developmentAvailable` to unified equipment sources schema 2. The formal value comes from KCWiki `_buildable`, while WikiWiki independently validates the current equipment infobox `備考` marker。
- Added source diagnostics for KCWiki/WikiWiki development-availability cross-validation; null, non-boolean, and conflicting values stop package generation with a red error。
- Added improvement detail schema 4 with source-faithful ★0..★MAX `levelExpectations`。
- Added fixed 11-row route `stepList` data for every normal improvement level and optional MAX conversion。
- Preserved conditional effect text separately from simple numeric values so consumers do not apply context-specific bonuses globally。
- Added the MAX conversion target name so consumers can render the upgrade result without a separate equipment-master lookup。
- Added `schemas/improvement-detail.schema.json` for the schema 4 record contract。

### 修复

- Restored ship-acquisition relations for Start2 equipment IDs 142 and 305 when KcWiki uses English “Kai Ni” aliases instead of its canonical equipment names。
- Added source-scoped, Start2-validated semantic aliases so accepted upstream naming variants cannot silently disappear from the package。

### 兼容性

- Improvement list schema: 2 (unchanged)。
- Improvement detail schema: 4。
- Equipment sources schema: 2 (`developmentAvailable` is newly required)。
- Consumers that only read existing improvement-detail fields remain compatible; equipment-source consumers must accept the required boolean field。

### 数据快照

数据包版本：`@sakura2333/kancolle-data@0.5.1`

- 改修路线明细：372
- 装备获得记录：247
- 特殊装备加成记录：348
- 消耗品图片：16

### 数据边界

- `dist/data-pipeline/sources/` 提供可公开的来源诊断数据，但不属于 npm 消费接口。
- 原始网页缓存和本机运行状态不属于公开数据集。
