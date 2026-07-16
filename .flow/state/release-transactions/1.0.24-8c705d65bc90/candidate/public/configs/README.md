# Project configuration governance

All shared project configuration belongs under `configs/`.

Committed configuration is limited to project rules, schemas, and reusable templates. Machine-local, private, cookie, token, browser-session, proxy, and runtime configuration must stay out of Git.

## Layout

- `configs/*.json`: shared project configuration used by source parsing, validation, generated-state, and reliability rules.
- `configs/*.default.json`: committed defaults used to materialize ignored `configs/*.local.*` files.
- `configs/schemas/`: optional schemas for committed configuration contracts.
- `configs/*.local.*`: canonical machine-local configuration files created from committed defaults.
- `configs/local/`: optional ignored directory for operator-managed local configuration that does not have a canonical file path.

## Ignore policy

The generated public `.gitignore` is ordered by responsibility:

1. Project-controlled local and generated paths are listed explicitly.
2. Private, secret, cookie, session, and token filename patterns are defensive fallbacks for names the project cannot enumerate in advance.
3. Tool and platform noise is kept in a separate final section.

Defensive filename patterns are not supported configuration contracts. A reusable configuration must still have a committed default or schema and an explicit runtime loader.

## Rules

- Do not commit `*.local.*`, `*.private.*`, `*.secret.*`, cookie, token, or session files.
- Do not keep project configuration templates under `tools/` or `service/`; those directories contain logic and CLI shells.
- Local WikiWiki browser-session configuration is created from `configs/wikiwiki-crawler.default.json` and stored as ignored `configs/wikiwiki-crawler.local.json`. Runtime cache, receipt, and browser profile stay under `.spider/local/`.
- Generated data, source caches, reports, and package staging outputs are runtime artifacts. They must stay ignored or be exported through the public automation pipeline, never mixed into code commits.
