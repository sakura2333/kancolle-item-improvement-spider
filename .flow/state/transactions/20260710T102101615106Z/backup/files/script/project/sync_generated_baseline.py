#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from _common import PROJECT_ROOT, ProjectCommandError, main_guard, project_env, run, write_json

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service.generated_state import GeneratedStateError
from service.generated_state.sync import (
    apply_generated_baseline,
    build_sync_report,
    restore_generated_baseline,
)


def _project_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    expanded = path.expanduser()
    return expanded.resolve() if expanded.is_absolute() else (PROJECT_ROOT / expanded).resolve()


def _default_backup(build_id: str | None) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = str(build_id or "unknown").replace("/", "-")
    return PROJECT_ROOT / "dist" / "generated-state-backups" / f"{stamp}-{suffix}"


def _verify_after_apply(report: dict, *, skip_verify: bool) -> None:
    run(
        [sys.executable, "-m", "service.data_package.cli", "refresh-manifest"],
        cwd=PROJECT_ROOT,
        env=project_env(),
    )
    if not skip_verify:
        run(
            [sys.executable, "script/project/verify.py"],
            cwd=PROJECT_ROOT,
            env=project_env(),
        )
    report["verifiedAfterApply"] = not skip_verify


def execute(args: argparse.Namespace) -> None:
    state_root = _project_path(args.state_dir)
    try:
        report = build_sync_report(state_root=state_root, project_root=PROJECT_ROOT)
        if args.apply:
            backup_dir = _project_path(args.backup_dir) or _default_backup(report.get("buildId"))
            report = apply_generated_baseline(
                state_root=state_root,
                project_root=PROJECT_ROOT,
                backup_dir=backup_dir,
            )
            if report.get("applied"):
                try:
                    _verify_after_apply(report, skip_verify=args.skip_verify)
                except Exception as original_error:
                    try:
                        restore_generated_baseline(
                            project_root=PROJECT_ROOT,
                            backup_dir=Path(str(report["backupDir"])),
                            paths=report["paths"],
                            originally_present=report["originallyPresent"],
                        )
                    except Exception as restore_error:
                        raise ProjectCommandError(
                            "应用 generated-state 后验证失败，且自动回滚失败："
                            f"验证错误={original_error}; 回滚错误={restore_error}"
                        ) from restore_error
                    raise
            else:
                report["verifiedAfterApply"] = None
        else:
            report["applied"] = False
    except (GeneratedStateError, OSError, ValueError) as exc:
        raise ProjectCommandError(str(exc)) from exc

    if args.report_json:
        try:
            write_json(_project_path(args.report_json), report)
        except (OSError, ValueError) as exc:
            raise ProjectCommandError(str(exc)) from exc
    print(json.dumps(report, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="显式选择 generated-state 数据作为 dev 的完整开发基线"
    )
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="默认仅输出差异；指定后才写入")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args()
    return main_guard(lambda: execute(args))


if __name__ == "__main__":
    raise SystemExit(main())
