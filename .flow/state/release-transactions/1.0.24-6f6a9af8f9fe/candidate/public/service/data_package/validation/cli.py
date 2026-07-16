from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.data_package.builder import PACKAGE_DIR

from .baseline import validate_package
from .constants import DEFAULT_CONFIG_PATH
from .snapshot import write_snapshot

def main():
    parser = argparse.ArgumentParser(description="Snapshot and validate the published KanColle data package")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--output", required=True, type=Path)
    snapshot_parser.add_argument("--package-dir", type=Path, default=PACKAGE_DIR)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--baseline", required=True, type=Path)
    validate_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    validate_parser.add_argument("--package-dir", type=Path, default=PACKAGE_DIR)
    validate_parser.add_argument("--output", type=Path)

    args = parser.parse_args()
    if args.command == "snapshot":
        snapshot = write_snapshot(args.output, args.package_dir, require_fresh_sources=False)
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return

    snapshot, changed = validate_package(args.baseline, args.config, args.package_dir)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"changed": changed, **snapshot}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
