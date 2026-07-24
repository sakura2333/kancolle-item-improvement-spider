# Public source evidence

This directory is not an npm consumer API. Public `main` keeps only stable source metadata, accepted structured snapshots and aggregate summaries needed for traceability or clean builds.

## Retained datasets

- `akashi-list/metadata.json`, `wikiwiki-jp/metadata.json`, `kcwiki-data/metadata.json`: source health and parse-count summaries.
- `kcwiki-data/`: accepted equipment drop-from projection, dataset issues and dataset metadata.
- `kc3-slotitem-bonus/`: accepted special-bonus projection, dataset issues and dataset metadata.
- `equipment-sources/`: unified equipment-source projection and input-hash metadata.
- `wikiwiki-equipment-detail/`: validated six-file acquisition snapshot used when Raw Cache is absent.
- `reliability/summary.json`: advisory relative-consistency summary; it never participates in canonical source election.

Runtime normalized facts, parser worksets, cross-source differences, AI review bundles, full history snapshots and per-run deltas are intentionally excluded from public `main`. Original HTML, HTTP cache, cookies, headers, proxy details and local paths are never published.
