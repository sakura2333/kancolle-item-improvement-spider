#!/usr/bin/env bash
set -euo pipefail
TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$TOOL_DIR/../.." && pwd)"
exec python3 "$TOOL_DIR/crawler.py" --project "$PROJECT_ROOT" "$@"
