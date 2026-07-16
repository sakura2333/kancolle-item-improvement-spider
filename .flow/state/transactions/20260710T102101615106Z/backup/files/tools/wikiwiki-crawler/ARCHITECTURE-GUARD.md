# WikiWiki crawler architecture guard

## Classification

This directory is the low-level implementation for a **manual browser-session acquisition source**. It is not part of the default Spider data run, CI release path, or npm package. The formal public entry is the thin `./flow wikiwiki` wrapper, which may execute this tool only as an explicit manual command.

## Hard boundaries

- Core project code must not import this directory or depend on its Python modules.
- The only allowed project entry is a thin subprocess wrapper for the explicit manual `./flow wikiwiki` command.
- CI, npm, default checks, release, and the normal `./flow run` Spider pipeline must not execute browser-session crawling.
- The tool may read exported Start2 data, capture Wiki card-list pages, and build local name-to-URL catalogs; this is a one-way dependency.
- Wiki card numbers are extraction hints only. Entity association must use exact or conservatively normalized names, and unresolved names must not trigger guessed detail-page requests.
- Update artifacts may distribute these files, but update/release transactions must not execute browser-session crawling.
- Cookies, browser headers, checkpoints, temporary downloads, and logs belong under `.flow/local/**`. Accepted raw HTML is written to local-preserved `.flow/local/source-cache/**` so the offline parser can reuse the normal cache layout. Neither location is project-owned state.

## AI reading rule

During ordinary core review, architecture analysis, or refactoring, exclude this directory from the core dependency graph. Read it only when the request explicitly concerns WikiWiki browser-session acquisition or its captured evidence.

This guard classifies the directory; it does not override actual code dependencies. Any direct core import from this directory is a defect.
