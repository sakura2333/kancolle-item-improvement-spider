# Release Notes

## 1.0.24 (2026-07-10)

本页由发布候选生成器汇总数据包 Changelog、机器发布记录和本次 Git 变更后生成。只保留面向使用者和数据消费方的摘要。

### 新增

- Added official KanColle `useitem/card` and `slot/card` acquisition so Akashi remains a business-data source only。
- Added WebP quality 93 canonical assets for both 390×390 equipment cards and 270×270 useitem cards；the legacy `improvement2` variant retains only useitem PNGs。
- Added improvement detail schema 4 with source-faithful ★0..★MAX `levelExpectations`。
- Added fixed 11-row route `stepList` data for every normal improvement level and optional MAX conversion。
- Preserved conditional effect text separately from simple numeric values so consumers do not apply context-specific bonuses globally。
- Added the MAX conversion target name so consumers can render the upgrade result without a separate equipment-master lookup。
- Added `schemas/improvement-detail.schema.json` for the schema 4 record contract。

### 修复

- Changed all image-cache expiration from 30 days to 180 days and froze official originals in the Source Bundle before offline package projection。
- Reduced `improvement2` to its actual legacy boundary: schema-3 improvement data plus `assets/useitem/{id}.png`; equipment datasets and equipment images are no longer copied into that npm variant。
- Removed Akashi page image URLs from the asset pipeline and added Start2 ID/version validation plus WebP signature and manifest-schema checks。
- Moved npm Registry artifact hydration out of an invalid indented Workflow heredoc into the verified release-set module, and added `bash -n` validation for every public Workflow `run` block。
- Changed validated data updates to publish the frozen `latest` and `improvement2` npm artifacts automatically, then advance `online`; the manual Release workflow remains available for recovery and reconciliation。
- Reworked npm publication idempotency around one package-business identity method: Data Build packs canonical and `improvement2`, compares both actual tgz payloads with npm Registry tarballs, reuses the existing patch only when both business payloads match, repairs missing variants, dist-tags, or `online`, and allocates the next patch when either variant changes。
- Removed release-history self-reported digests from version decisions. The npm business identity now covers data, runtime entry code, type declarations, schemas, validation scripts, and stable package metadata while excluding version, generated manifest, README, changelog, release history, license summary, and audit output。
- Preserved both stdout and stderr in npm failure audits and changed credential validation from a non-empty secret check to a real `npm whoami` registry request。
- Fixed Source Bundle input closure so Acquire prefetches and seals the complete `kcQuests/quests-scn.json` catalog before cache-only Build starts。
- Fixed GitHub Artifact uploads so hidden Source Bundle and generated-state directories are preserved instead of being filtered before offline verification。
- Clarified the npm directory contract: `packages/kancolle-data/` is the tracked source template, `dist/packages/kancolle-data/` is the complete generated candidate, and `dist/npm/kancolle-data/<version>/` contains isolated publish artifacts。
- Restored ship-acquisition relations for Start2 equipment IDs 142 and 305 when KcWiki uses English “Kai Ni” aliases instead of its canonical equipment names。
- Added source-scoped, Start2-validated semantic aliases so accepted upstream naming variants cannot silently disappear from the package。

### 兼容性

- Improvement list schema: 2 (unchanged)。
- Improvement detail schema: 4。
- Consumers that only read existing detail fields remain compatible; schema-aware validators must accept version 4。

### 数据快照

数据包版本：`@sakura2333/kancolle-data@0.5.1`

- 改修路线明细：372
- 装备获得记录：247
- 特殊装备加成记录：348
- 消耗品图片：16

### 数据边界

- `dist/data-pipeline/sources/` 提供可公开的来源诊断数据，但不属于 npm 消费接口。
- 原始网页缓存和本机运行状态不属于公开数据集。
