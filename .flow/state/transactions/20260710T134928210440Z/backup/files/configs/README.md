# Project configuration governance

All shared project configuration belongs under `configs/`.

Committed configuration is limited to project rules, schemas, and reusable templates. Machine-local, private, cookie, token, browser-session, proxy, and runtime configuration must stay out of Git.

## Layout

- `configs/*.json`: shared project configuration used by source parsing, validation, generated-state, and reliability rules.
- `configs/*.default.json`: committed default configuration used to materialize ignored `configs/*.local.*` files.
- `configs/schemas/`: optional schemas for committed configuration contracts.
- `configs/local/`: ignored local configuration.

## Rules

- Do not commit `*.local.*`, `*.private.*`, `*.secret.*`, cookie, token, or session files.
- Do not keep project configuration templates under `tools/` or `service/`; those directories contain logic and CLI shells.
- Local WikiWiki browser-session configuration is created from `configs/wikiwiki-crawler.default.json` and stored as ignored `configs/wikiwiki-crawler.local.json`. Runtime cache, receipt, and browser profile stay under `.flow/local/`.
- Generated data, source caches, reports, and package staging outputs are runtime artifacts. They must stay ignored or be exported through the public automation pipeline, never mixed into code commits.
