#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from _common import PROJECT_ROOT, ProjectCommandError, main_guard, write_json

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service.generated_state import (
    GeneratedStateError,
    create_generated_state_artifact,
    export_generated_state,
    verify_generated_state,
    verify_generated_state_artifact,
)


def _project_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    expanded = path.expanduser()
    return expanded.resolve() if expanded.is_absolute() else (PROJECT_ROOT / expanded).resolve()


def _emit_result(result: dict, result_json: Path | None) -> None:
    if result_json is not None:
        write_json(_project_path(result_json), result)
    print(json.dumps(result, ensure_ascii=False))


def _export(args: argparse.Namespace) -> None:
    try:
        result = export_generated_state(
            project_root=PROJECT_ROOT,
            output_dir=_project_path(args.output_dir),
            base_ref=args.base_ref,
            base_commit=args.base_commit,
            verification_report=_project_path(args.verification_report),
            npm_audit=_project_path(args.npm_audit),
            build_id=args.build_id,
            replace=args.replace,
        )
        _emit_result(result, args.result_json)
    except (GeneratedStateError, OSError, ValueError) as exc:
        raise ProjectCommandError(str(exc)) from exc


def _verify(args: argparse.Namespace) -> None:
    try:
        result = verify_generated_state(_project_path(args.state_dir))
        _emit_result(result, args.result_json)
    except (GeneratedStateError, OSError, ValueError) as exc:
        raise ProjectCommandError(str(exc)) from exc



def _archive(args: argparse.Namespace) -> None:
    try:
        result = create_generated_state_artifact(
            state_root=_project_path(args.state_dir),
            output_file=_project_path(args.output_file),
            receipt_file=_project_path(args.receipt_json),
            replace=args.replace,
        )
        _emit_result(result, args.result_json)
    except (GeneratedStateError, OSError, ValueError) as exc:
        raise ProjectCommandError(str(exc)) from exc


def _verify_archive(args: argparse.Namespace) -> None:
    try:
        result = verify_generated_state_artifact(
            archive_file=_project_path(args.archive_file),
            receipt_file=_project_path(args.receipt_json),
        )
        _emit_result(result, args.result_json)
    except (GeneratedStateError, OSError, ValueError) as exc:
        raise ProjectCommandError(str(exc)) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="导出或校验纯 generated-state")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="导出纯数据状态目录")
    export_parser.add_argument("--output-dir", type=Path, required=True)
    export_parser.add_argument("--base-ref", default="main")
    export_parser.add_argument("--base-commit")
    export_parser.add_argument("--build-id")
    export_parser.add_argument("--verification-report", type=Path)
    export_parser.add_argument("--npm-audit", type=Path)
    export_parser.add_argument("--result-json", type=Path)
    export_parser.add_argument("--replace", action="store_true")
    export_parser.set_defaults(action=_export)

    verify_parser = subparsers.add_parser("verify", help="校验 generated-state 完整性")
    verify_parser.add_argument("--state-dir", type=Path, required=True)
    verify_parser.add_argument("--result-json", type=Path)
    verify_parser.set_defaults(action=_verify)

    archive_parser = subparsers.add_parser("archive", help="生成不可变 generated-state ZIP")
    archive_parser.add_argument("--state-dir", type=Path, required=True)
    archive_parser.add_argument("--output-file", type=Path, required=True)
    archive_parser.add_argument("--receipt-json", type=Path)
    archive_parser.add_argument("--result-json", type=Path)
    archive_parser.add_argument("--replace", action="store_true")
    archive_parser.set_defaults(action=_archive)

    verify_archive_parser = subparsers.add_parser(
        "verify-archive", help="校验 generated-state ZIP 和可选 receipt"
    )
    verify_archive_parser.add_argument("--archive-file", type=Path, required=True)
    verify_archive_parser.add_argument("--receipt-json", type=Path)
    verify_archive_parser.add_argument("--result-json", type=Path)
    verify_archive_parser.set_defaults(action=_verify_archive)

    args = parser.parse_args()
    return main_guard(lambda: args.action(args))


if __name__ == "__main__":
    raise SystemExit(main())
