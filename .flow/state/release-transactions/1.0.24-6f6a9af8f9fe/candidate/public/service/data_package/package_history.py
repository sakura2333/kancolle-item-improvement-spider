from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from service.data_package.package_paths import PACKAGE_DIR

CHANGELOG_PATH = PACKAGE_DIR / "CHANGELOG.md"
RELEASES_PATH = PACKAGE_DIR / "RELEASES.json"


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _release_markdown(version: str, date: str, snapshot: dict) -> str:
    metrics = snapshot.get("metrics", {})
    return "\n".join(
        [
            f"## [{version}] - {date}",
            "",
            "### Data",
            "",
            "- Refreshed validated KanColle consumer datasets after a successful strict Spider run.",
            f"- Improvement records: {metrics.get('improvement.detailRecordCount', 'unknown')}.",
            f"- Equipment acquisition records: {metrics.get('equipmentDropFrom.recordCount', 'unknown')}.",
            f"- Equipment special-bonus records: {metrics.get('equipmentSpecialBonuses.recordCount', 'unknown')}.",
            f"- Equipment-type special-bonus records: {metrics.get('equipmentSpecialBonuses.equipmentTypeRecordCount', 'unknown')}.",
            f"- Packaged use-item icons: {metrics.get('useitemIcons.count', 'unknown')}.",
            "",
            "### Validation",
            "",
            "- Passed source freshness, schema, reference-integrity, record-count, and file-size quality gates.",
            "",
        ]
    )


def _insert_changelog_release(version: str, date: str, snapshot: dict) -> None:
    text = CHANGELOG_PATH.read_text(encoding="utf-8")
    if f"## [{version}]" in text:
        return
    unreleased = text.find("## [Unreleased]")
    if unreleased < 0:
        raise ValueError("CHANGELOG.md does not contain an Unreleased section")
    next_release = text.find("\n## [", unreleased + len("## [Unreleased]"))
    block = _release_markdown(version, date, snapshot)
    if next_release < 0:
        text = text.rstrip() + "\n\n" + block
    else:
        text = text[:next_release].rstrip() + "\n\n" + block + text[next_release:]
    CHANGELOG_PATH.write_text(text.rstrip() + "\n", encoding="utf-8")


def finalize_release(version: str, snapshot_path: Path) -> dict:
    snapshot = _read_json(snapshot_path, {})
    if not isinstance(snapshot, dict):
        raise ValueError("release snapshot must contain a JSON object")
    date = datetime.now(timezone.utc).date().isoformat()
    _insert_changelog_release(version, date, snapshot)

    releases = _read_json(RELEASES_PATH, [])
    if not isinstance(releases, list):
        raise ValueError("RELEASES.json must contain an array")
    entry = {
        "version": version,
        "date": date,
        "contentDigest": snapshot.get("contentDigest"),
        "metrics": snapshot.get("metrics", {}),
    }
    releases = [value for value in releases if value.get("version") != version]
    releases.insert(0, entry)
    RELEASES_PATH.write_text(
        json.dumps(releases, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return entry
