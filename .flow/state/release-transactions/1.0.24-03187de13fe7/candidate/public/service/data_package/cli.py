from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from service.data_package.builder import build_data_package, refresh_package_manifest
from service.data_package.package_paths import PACKAGE_DIR, PACKAGE_SOURCE_DIR
from service.data_package.package_history import finalize_release
from service.operator_stop import OperatorStopError, write_operator_stop
from service.data_package.versioning import (
    VersionPlanError,
    plan_manual_version,
    plan_scheduled_version,
)

_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _run_strict_spider() -> None:
    # Strict package generation refreshes the canonical Akashi projection in
    # the same process so process-local fetch audits cannot be bypassed.
    os.environ["DATA_PACKAGE_STRICT"] = "1"
    os.environ["VALIDATION_STRICT"] = "1"
    from service.akashi_list.akashi_list_spider import process
    from util.start2.start2_utils import update_start2_if_needed

    update_start2_if_needed()
    process()


def _write_version(version: str) -> str:
    clean = version.strip()
    if _SEMVER_RE.fullmatch(clean) is None:
        raise ValueError(f"invalid semantic version: {version!r}")

    for package_path in (PACKAGE_SOURCE_DIR / "package.json", PACKAGE_DIR / "package.json"):
        if not package_path.exists():
            continue
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package["version"] = clean
        package_path.write_text(
            json.dumps(package, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    manifest_path = PACKAGE_DIR / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["packageVersion"] = clean
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return clean


def _read_published_versions(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload is None:
        return []
    if isinstance(payload, str):
        return [payload]
    if not isinstance(payload, list):
        raise ValueError("published versions file must contain a JSON array")
    return [str(value) for value in payload]


def _write_json_result(payload: dict, output: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build, validate and prepare the KanColle consumer data package"
    )
    parser.add_argument(
        "command",
        choices=[
            "build",
            "refresh-manifest",
            "plan-version",
            "set-version",
            "finalize-release",
        ],
    )
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--version")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--mode", choices=["scheduled", "manual"])
    parser.add_argument("--bump", choices=["none", "patch", "minor", "major"], default="none")
    parser.add_argument("--published-versions", type=Path)
    parser.add_argument("--data-changed", choices=["true", "false"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.command == "refresh-manifest":
        print(json.dumps(refresh_package_manifest(), ensure_ascii=False))
        return 0

    if args.command == "set-version":
        if not args.version:
            parser.error("set-version requires --version X.Y.Z")
        print(_write_version(args.version))
        return 0

    if args.command == "finalize-release":
        if not args.version or not args.snapshot:
            parser.error("finalize-release requires --version X.Y.Z --snapshot PATH")
        print(json.dumps(finalize_release(args.version, args.snapshot), ensure_ascii=False))
        return 0

    if args.command == "plan-version":
        if not args.mode or not args.published_versions:
            parser.error("plan-version requires --mode and --published-versions")
        package = json.loads((PACKAGE_SOURCE_DIR / "package.json").read_text(encoding="utf-8"))
        repository_version = str(package["version"])
        published_versions = _read_published_versions(args.published_versions)
        try:
            if args.mode == "scheduled":
                if args.data_changed is None:
                    parser.error("scheduled plan-version requires --data-changed true|false")
                plan = plan_scheduled_version(
                    repository_version,
                    published_versions,
                    data_changed=args.data_changed == "true",
                )
            else:
                plan = plan_manual_version(
                    repository_version,
                    published_versions,
                    bump=args.bump,
                )
        except VersionPlanError as exc:
            parser.error(str(exc))
        _write_json_result(plan.to_json(), args.output)
        return 0

    try:
        if args.strict:
            _run_strict_spider()
        else:
            build_data_package(strict=False)
    except OperatorStopError as exc:
        # CI and local wrappers may redirect this process into a log file, so isatty() is false.
        # Force ANSI red here; run_logged replays the tail to the terminal.
        write_operator_stop(exc, color=True)
        return exc.exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
