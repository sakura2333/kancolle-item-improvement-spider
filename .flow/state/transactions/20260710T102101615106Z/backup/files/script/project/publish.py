#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from _common import PROJECT_ROOT, ProjectCommandError, main_guard, require_tool

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from _npm_registry import NpmPublishError, reconcile_npm_publish


def _project_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    expanded = path.expanduser()
    return expanded.resolve() if expanded.is_absolute() else (PROJECT_ROOT / expanded).resolve()


def execute(args: argparse.Namespace) -> None:
    require_tool("npm")
    if args.retries < 1:
        raise ProjectCommandError("--retries 必须大于等于 1")
    if args.retry_delay < 0:
        raise ProjectCommandError("--retry-delay 不能小于 0")

    try:
        result = reconcile_npm_publish(
            package_result_path=_project_path(args.package_result),
            audit_output=_project_path(args.audit_output),
            tag=args.tag,
            registry=args.registry,
            publish=args.publish,
            provenance_manifest=_project_path(args.provenance_manifest),
            retries=args.retries,
            retry_delay=args.retry_delay,
        )
    except (NpmPublishError, OSError, ValueError) as exc:
        raise ProjectCommandError(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="幂等发布并对账唯一 npm tarball")
    parser.add_argument("--package-result", type=Path, required=True)
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=Path("dist/npm/npm-publish-audit.json"),
    )
    parser.add_argument("--provenance-manifest", type=Path)
    parser.add_argument("--registry")
    parser.add_argument("--tag", default="latest")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="默认只查询并生成审计；指定后才允许执行 npm publish",
    )
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    args = parser.parse_args()
    return main_guard(lambda: execute(args))


if __name__ == "__main__":
    raise SystemExit(main())
