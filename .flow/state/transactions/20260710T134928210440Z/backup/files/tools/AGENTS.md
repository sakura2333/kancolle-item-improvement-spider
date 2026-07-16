# External Tooling Scope

This file applies to `tools/**` only.

- `tools/**` is external, manually invoked tooling and is outside the L1-L4 runtime architecture.
- Do not import `tools/**` from `flow`, `script`, `service`, `configs`, or `packages`.
- A tool may read exported project data or invoke a documented project entry through a subprocess. This dependency is one-way: core code must never depend on the tool.
- Do not register tools as Flow commands, CI jobs, npm scripts, or default quality steps unless a human explicitly promotes the tool into the project architecture.
- Local credentials, cookies, browser headers, checkpoints, and logs must stay under `.flow/local/**`. Raw pages approved for parser reuse are written to local-preserved `.flow/local/source-cache/**`; neither location may be committed or printed with credentials.
- When reviewing or refactoring the core project, exclude `tools/**` unless the task explicitly targets external tooling or data acquisition.
