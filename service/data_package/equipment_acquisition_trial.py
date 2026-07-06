from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.data_package.equipment_acquisition_crawl import (
    DEFAULT_OUTPUT_DIR,
    run_full_crawl,
)

DEFAULT_EQUIPMENT_IDS = [3, 161, 419, 533]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compatibility wrapper for a bounded WikiWiki equipment acquisition crawl"
    )
    parser.add_argument(
        "--equipment-id",
        action="append",
        type=int,
        dest="equipment_ids",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "trial",
    )
    parser.add_argument("--delay", type=float, default=0.35)
    args = parser.parse_args()
    metadata = run_full_crawl(
        output_dir=args.output_dir,
        equipment_ids=args.equipment_ids or DEFAULT_EQUIPMENT_IDS,
        delay_seconds=max(args.delay, 0.0),
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
