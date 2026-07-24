# Changelog

All notable consumer-visible changes to `@sakura2333/kancolle-data` are documented here.

## [Unreleased]

### Added

- Added improvement detail schema 4 with source-faithful ★0..★MAX `levelExpectations`.
- Added fixed 11-row route `stepList` data for every normal improvement level and optional MAX conversion.
- Preserved conditional effect text separately from simple numeric values so consumers do not apply context-specific bonuses globally.
- Added the MAX conversion target name so consumers can render the upgrade result without a separate equipment-master lookup.
- Added `schemas/improvement-detail.schema.json` for the schema 4 record contract.

### Fixed

- Restored ship-acquisition relations for Start2 equipment IDs 142 and 305 when KcWiki uses English “Kai Ni” aliases instead of its canonical equipment names.
- Added source-scoped, Start2-validated semantic aliases so accepted upstream naming variants cannot silently disappear from the package.

### Compatibility

- Improvement list schema: 2 (unchanged).
- Improvement detail schema: 4.
- Consumers that only read existing detail fields remain compatible; schema-aware validators must accept version 4.

### Planned

- Add quest, development, exchange, ranking, and event acquisition methods.
- Add additional ship, map, and quest projections when stable schemas are available.

## [0.5.26] - 2026-07-24

### Data

- Refreshed validated KanColle consumer datasets after a successful strict Spider run.
- Improvement records: 372.
- Equipment acquisition records: 252.
- Equipment special-bonus records: 362.
- Equipment-type special-bonus records: 7.
- Packaged use-item icons: 16.

### Validation

- Passed source freshness, schema, reference-integrity, record-count, and file-size quality gates.

## [0.5.25] - 2026-07-23

### Data

- Refreshed validated KanColle consumer datasets after a successful strict Spider run.
- Improvement records: 372.
- Equipment acquisition records: 252.
- Equipment special-bonus records: 362.
- Equipment-type special-bonus records: 7.
- Packaged use-item icons: 16.

### Validation

- Passed source freshness, schema, reference-integrity, record-count, and file-size quality gates.

## [0.5.24] - 2026-07-22

### Data

- Refreshed validated KanColle consumer datasets after a successful strict Spider run.
- Improvement records: 372.
- Equipment acquisition records: 252.
- Equipment special-bonus records: 362.
- Equipment-type special-bonus records: 7.
- Packaged use-item icons: 16.

### Validation

- Passed source freshness, schema, reference-integrity, record-count, and file-size quality gates.

## [0.5.23] - 2026-07-21

### Data

- Refreshed validated KanColle consumer datasets after a successful strict Spider run.
- Improvement records: 372.
- Equipment acquisition records: 252.
- Equipment special-bonus records: 362.
- Equipment-type special-bonus records: 7.
- Packaged use-item icons: 16.

### Validation

- Passed source freshness, schema, reference-integrity, record-count, and file-size quality gates.

## [0.5.22] - 2026-07-20

### Data

- Refreshed validated KanColle consumer datasets after a successful strict Spider run.
- Improvement records: 372.
- Equipment acquisition records: 252.
- Equipment special-bonus records: 362.
- Equipment-type special-bonus records: 7.
- Packaged use-item icons: 16.

### Validation

- Passed source freshness, schema, reference-integrity, record-count, and file-size quality gates.

## [0.5.21] - 2026-07-19

### Data

- Refreshed validated KanColle consumer datasets after a successful strict Spider run.
- Improvement records: 372.
- Equipment acquisition records: 249.
- Equipment special-bonus records: 350.
- Equipment-type special-bonus records: 7.
- Packaged use-item icons: 16.

### Validation

- Passed source freshness, schema, reference-integrity, record-count, and file-size quality gates.

## [0.5.20] - 2026-07-18

### Data

- Refreshed validated KanColle consumer datasets after a successful strict Spider run.
- Improvement records: 372.
- Equipment acquisition records: 249.
- Equipment special-bonus records: 350.
- Equipment-type special-bonus records: 7.
- Packaged use-item icons: 16.

### Validation

- Passed source freshness, schema, reference-integrity, record-count, and file-size quality gates.

## [0.5.19] - 2026-07-17

### Data

- Refreshed validated KanColle consumer datasets after a successful strict Spider run.
- Improvement records: 372.
- Equipment acquisition records: 249.
- Equipment special-bonus records: 350.
- Equipment-type special-bonus records: 7.
- Packaged use-item icons: 16.

### Validation

- Passed source freshness, schema, reference-integrity, record-count, and file-size quality gates.

## [0.2.0] - 2026-06-28

### Added

- Added equipment-type targets to the KC3 special-bonus dataset instead of discarding rules that apply to an entire equipment category.
- Added use-item icon `71.png` to the shared package.
- Added required, available, and missing use-item ID lists to the icon manifest.
- Added `RELEASES.json` for machine-readable release metrics and content digests.
- Added per-source fetch audits containing freshness, cache-fallback, validation-time, and content-hash information.
- Added a prepublish freshness hook that rejects cache-only or stale package builds.

### Changed

- Upgraded the equipment special-bonus schema from version 1 to version 2.
- Special-bonus records now expose a `target` union for concrete equipment IDs or equipment-type IDs.
- Package publication now commits and pushes the prepared release state before npm publication, allowing a failed npm upload to be resumed without inventing another version.
- Automatic patch releases generate a versioned data summary in this changelog.

### Fixed

- Fixed seven KC3 equipment-type bonus groups being reported as missing equipment IDs and omitted from public data.
- Fixed referenced use-item icons being able to disappear while the package still passed its count-only quality gate.
- Fixed strict publication accepting stale cached source data after a network failure.

### Compatibility

- Improvement list schema: 2.
- Improvement detail schema: 3.
- Equipment drop-from schema: 1.
- Equipment special-bonus schema: 2.

## [0.1.1] - 2026-06-28

### Fixed

- Added normalized `range` values for KC3 special equipment bonuses sourced from the upstream `leng` field.
- Fixed range-only bonus rules being rejected as empty bonus records during automatic publication.

### Changed

- Added automatic data-only patch publication after successful strict Spider runs.
- Added count, shape, source-status, and file-size release gates.

## [0.1.0] - 2026-06-28

### Added

- Added compact all-days and weekday improvement list data.
- Added route-complete improvement detail data.
- Added equipment acquisition sources derived from ship initial and remodel loadouts.
- Added equipment special bonus rules scoped by ship, class, type, country, improvement level, equipment count, and equipment requirements.
- Added use-item PNG assets.
- Added top-level and dataset manifests with source metadata, schema versions, data versions, and file hashes.
- Added JSON Schemas, TypeScript declarations, and stable file-path exports.
- Added audit build reports without publishing raw HTML snapshots.

### Compatibility

- Improvement list schema: 2.
- Improvement detail schema: 3.
- Equipment drop-from schema: 1.
- Equipment special-bonus schema: 1.
