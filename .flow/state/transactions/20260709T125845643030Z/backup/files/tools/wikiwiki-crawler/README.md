# WikiWiki browser-session acquisition

This tool is the low-level implementation for the project's formal WikiWiki equipment-detail browser-session source. Use `./flow wikiwiki` for normal maintenance. Call this script directly only when debugging the acquisition layer.

## Local configuration

```bash
./flow wikiwiki config
chmod 600 configs/wikiwiki-crawler.local.json
```

The recommended mode is `transport=playwright`. Install the optional browser dependency and browser runtime:

```bash
python3 -m pip install -r tools/wikiwiki-crawler/requirements.txt
python3 -m playwright install chromium
```

The browser profile under `.flow/local/wikiwiki-browser-profile/` persists cookies and local storage. On the same machine and network exit, bootstrap it once in a headed browser:

```bash
./flow wikiwiki session
```

If Cloudflare presents an interactive challenge, complete it in that browser window. Scheduled/headless runs may then reuse the same profile. The crawler does not solve CAPTCHAs, does not use stealth plugins, and stops if an interactive challenge returns.

The legacy `transport=curl` mode remains available. In that mode replace the example Cookie with a fresh browser session. Optional `headers` may carry browser client hints copied from cURL; do not copy page-specific conditional headers such as `if-none-match`.

## Build the Wiki index catalogs

Capture the three WikiWiki index pages.  Download is the slow phase; local
analysis is kept rerunnable and offline after the source receipt is ready.

```bash
python3 tools/wikiwiki-crawler/crawler.py catalog --kind all
```

The index-page HTML is stored in the shared Raw Cache. Derived catalogs, the
Start2 name-match report and the source receipt remain local crawler state:

```text
.flow/local/wikiwiki-crawler/
├── source-receipt.json
└── catalog/
    ├── equipment-pages.json     # locator-index
    ├── equipment-name-matches.json
    ├── ship-pages.json          # locator-index
    └── improvement-pages.json   # validation-index
```

`ship-pages.json` and `equipment-pages.json` are locator indexes used to collect
page URLs.  `improvement-pages.json` captures the improvement table for
cross-validation only; it is not an identity source.

The join does **not** use Wiki card numbers as entity IDs. It matches the Wiki
display name to the Start2 name using exact text first, conservative Unicode
normalization second, and the human-accepted one-way mappings in
`configs/wikiwiki-page-name-aliases.json` last. Full-width punctuation such as
`＋` therefore matches the corresponding Start2 `+`, while remodel suffixes and
parentheses remain part of the name. Ambiguous or unresolved names are reported
and are never requested by guessing a URL.

To rebuild catalogs from already captured list pages without network access:

```bash
python3 tools/wikiwiki-crawler/crawler.py catalog --kind all --offline
```

## Inspect

```bash
python3 tools/wikiwiki-crawler/crawler.py inspect
```

The inspection prints the resolved, ambiguous, and unresolved equipment-name
counts. Resolve catalog issues before starting a long crawl.

## Crawl or resume

```bash
./flow wikiwiki  # uses config.dailyLimit; template default: 30
```

Useful restrictions:

```bash
python3 tools/wikiwiki-crawler/crawler.py crawl --equipment-id 3 --equipment-id 12
python3 tools/wikiwiki-crawler/crawler.py crawl --from-id 100 --daily-limit 30
./flow wikiwiki --full
```

The daily quota is configured by `dailyLimit` in `configs/wikiwiki-crawler.local.json`; `--daily-limit` and legacy `--limit` are temporary per-run overrides. The quota counts only pages that still require a network fetch. Verified resume skips do not consume the quota. Captures older than `maxAgeDays` (default: 20) are selected for refresh, so the default quota of 30 completes one full verification cycle in about 20 days. Card-list catalogs use `catalogMaxAgeHours` (default: 22). `summary.json` records new, changed, unchanged, failed, remaining and next-equipment counts, including the resolved quota used for that run.

The crawler separates evidence from runtime state:

```text
.flow/local/source-cache/
├── _meta.json
└── wikiwiki.jp/kancolle/<URL-derived page path>

.flow/local/wikiwiki-crawler/
├── records.json
├── events.jsonl
├── summary.json
└── state/
```

Accepted HTML is installed atomically in the same raw HTTP cache layout consumed by the offline parser. `records.json`, retries, temporary downloads and logs remain crawler-private. Cookies stay only in `configs/wikiwiki-crawler.local.json`; browser sessions stay in the configured `browserProfileDir`.

The crawler is single-threaded, applies delay plus jitter, performs site-wide cooldown after HTTP 429, stops after repeated rate limits, and refuses to accept Cloudflare challenge pages as evidence. Any operator-required stop emits `ERROR`, exits non-zero, writes `operator-stop.json` with `stopReason`, states the manual action, and preserves a resumable checkpoint. Detail-page URLs come only from the Wiki-authored name catalog; the crawler no longer constructs URLs from Start2 names.

## Migrate captures from RC10 and earlier

Old captures under `.flow/local/wikiwiki-crawler/raw/*.html` can be registered in the shared raw cache without another network request:

```bash
python3 tools/wikiwiki-crawler/migrate_existing_html.py --dry-run
python3 tools/wikiwiki-crawler/migrate_existing_html.py
```

The migration is non-destructive by default. After verifying the summary, the old files may be removed safely:

```bash
python3 tools/wikiwiki-crawler/migrate_existing_html.py --remove-source
```

For a separately exported crawler directory:

```bash
python3 tools/wikiwiki-crawler/migrate_existing_html.py \
  --source /path/to/wikiwiki-crawler
```

Conflicting target content is rejected unless `--overwrite` is explicitly supplied. Every installed file is checked against the SHA-256 recorded by the crawler.

## Offline parsing

Parsing belongs to the project data layer and performs no network I/O:

```bash
PYTHONPATH=. .venv/bin/python script/project/equipment_acquisition.py
```

The parser discovers only raw-cache entries marked with `acquisition_source=external-browser-session-crawl`. It does not read `.flow/local/wikiwiki-crawler/records.json`.

## Formal Flow boundary

`./flow wikiwiki` is the formal manual trigger for this browser-session source. It refreshes or reuses the ship/equipment/improvement indexes, writes a source receipt, then runs the bounded equipment-detail crawl. It does not build the npm package, does not push Git, and does not publish data. Local parsing and cross-validation happen later in `./flow run`.

```bash
./flow wikiwiki
./flow wikiwiki --full
./flow wikiwiki session
```

`./flow run` remains the normal data pipeline. It consumes the raw cache through offline parsing and snapshot validation; it does not start a browser or try to clear Cloudflare during CI/release.
