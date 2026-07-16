# WikiWiki legacy migration tools

The formal WikiWiki acquisition implementation now lives in `automation/acquire/wikiwiki/` and is part of public main automation.

This dev-only directory retains only the one-time migration command and its regression tests:

```bash
mise exec -- uv run --locked python tools/wikiwiki-crawler/migrate_existing_html.py --dry-run
mise exec -- uv run --locked python tools/wikiwiki-crawler/migrate_existing_html.py
```

The migration registers old `.flow/local/wikiwiki-crawler/raw/*.html` captures in `.flow/local/source-cache/**`. It never publishes credentials or browser state.
