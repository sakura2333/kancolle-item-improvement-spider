from __future__ import annotations

import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from automation.release.consumer_identity import (
    CURRENT_VARIANT,
    IMPROVEMENT2_VARIANT,
    inspect_directory,
    inspect_tarball,
)


def _write_source_package(root: Path, *, generated_at: str, version: str) -> None:
    for relative in (
        "improvement",
        "compat/poi-plugin-item-improvement2/improvement",
        "equipment",
        "assets/equip",
        "assets/useitem",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps({"packageVersion": version, "generatedAt": generated_at}),
        encoding="utf-8",
    )
    (root / "RELEASES.json").write_text(
        json.dumps([{"version": version, "date": generated_at[:10]}]),
        encoding="utf-8",
    )
    (root / "improvement/list.json").write_text(
        json.dumps({"data": [[{"id": 1, "name": "A"}]]}, indent=2),
        encoding="utf-8",
    )
    canonical = {
        "id": 1,
        "name": "A",
        "improvementList": [
            {
                "baseResource": [1, 2, 3, 4],
                "stageList": [],
                "shipWeekList": [],
                "assistantShipIdsByDay": [],
                "routeId": "r1",
                "routeType": "normal",
                "stepList": [{"fromLevel": 0}],
            }
        ],
    }
    compatibility = {
        "id": 1,
        "name": "A",
        "improvementList": [
            {
                "baseResource": [1, 2, 3, 4],
                "stageList": [],
                "shipWeekList": [],
                "assistantShipIdsByDay": [],
                "routeId": "r1",
                "routeType": "normal",
            }
        ],
    }
    (root / "improvement/detail.nedb").write_text(
        json.dumps(canonical, indent=None) + "\n",
        encoding="utf-8",
    )
    compat_root = root / "compat/poi-plugin-item-improvement2"
    (compat_root / "manifest.json").write_text(
        json.dumps(
            {
                "packageVersion": f"{version}-improvement2",
                "generatedAt": generated_at,
                "consumer": "poi-plugin-item-improvement2",
            }
        ),
        encoding="utf-8",
    )
    (compat_root / "improvement/list.json").write_bytes(
        (root / "improvement/list.json").read_bytes()
    )
    (compat_root / "improvement/detail.nedb").write_text(
        json.dumps(compatibility) + "\n",
        encoding="utf-8",
    )
    for filename in ("drop-from.nedb", "sources.nedb", "special-bonuses.nedb"):
        (root / "equipment" / filename).write_text(
            json.dumps({"id": 1, "value": "stable"}) + "\n",
            encoding="utf-8",
        )
    (root / "assets/equip/1.png").write_bytes(b"equip")
    (root / "assets/useitem/1.png").write_bytes(b"useitem")


def _write_published_projection(source: Path, target: Path) -> None:
    for relative in ("improvement", "equipment", "assets/equip", "assets/useitem"):
        (target / relative).mkdir(parents=True, exist_ok=True)
    compat = source / "compat/poi-plugin-item-improvement2/improvement"
    (target / "improvement/list.json").write_bytes((compat / "list.json").read_bytes())
    (target / "improvement/detail.nedb").write_bytes((compat / "detail.nedb").read_bytes())
    for path in (source / "equipment").glob("*"):
        (target / "equipment" / path.name).write_bytes(path.read_bytes())
    (target / "assets/equip/1.png").write_bytes((source / "assets/equip/1.png").read_bytes())
    (target / "assets/useitem/1.png").write_bytes((source / "assets/useitem/1.png").read_bytes())


class ConsumerIdentityTest(unittest.TestCase):
    def test_versions_timestamps_and_release_history_do_not_change_identity(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name) / "package"
            _write_source_package(root, generated_at="2026-07-12T00:00:00Z", version="0.5.10")
            first_current = inspect_directory(root, variant=CURRENT_VARIANT)
            first_compat = inspect_directory(
                root,
                variant=IMPROVEMENT2_VARIANT,
                source_projection=True,
            )

            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "packageVersion": "0.5.99",
                        "generatedAt": "2026-07-13T23:59:59Z",
                    }
                ),
                encoding="utf-8",
            )
            (root / "compat/poi-plugin-item-improvement2/manifest.json").write_text(
                json.dumps(
                    {
                        "packageVersion": "0.5.99-improvement2",
                        "generatedAt": "2026-07-13T23:59:59Z",
                        "consumer": "poi-plugin-item-improvement2",
                    }
                ),
                encoding="utf-8",
            )
            (root / "RELEASES.json").write_text(
                json.dumps([{"version": "0.5.99", "date": "2026-07-13"}]),
                encoding="utf-8",
            )

            self.assertEqual(
                first_current["contentDigest"],
                inspect_directory(root, variant=CURRENT_VARIANT)["contentDigest"],
            )
            self.assertEqual(
                first_compat["contentDigest"],
                inspect_directory(
                    root,
                    variant=IMPROVEMENT2_VARIANT,
                    source_projection=True,
                )["contentDigest"],
            )

    def test_real_consumer_data_change_changes_identity(self):
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name) / "package"
            _write_source_package(root, generated_at="2026-07-12T00:00:00Z", version="0.5.10")
            before = inspect_directory(root, variant=CURRENT_VARIANT)["contentDigest"]
            (root / "equipment/sources.nedb").write_text(
                json.dumps({"id": 1, "value": "changed"}) + "\n",
                encoding="utf-8",
            )
            after = inspect_directory(root, variant=CURRENT_VARIANT)["contentDigest"]
            self.assertNotEqual(before, after)

    def test_directory_and_published_tarball_use_the_same_rules(self):
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            source = base / "source"
            published = base / "published"
            _write_source_package(source, generated_at="2026-07-12T00:00:00Z", version="0.5.10")
            _write_published_projection(source, published)
            expected = inspect_directory(
                source,
                variant=IMPROVEMENT2_VARIANT,
                source_projection=True,
            )["contentDigest"]
            tarball = base / "projection.tgz"
            with tarfile.open(tarball, "w:gz") as archive:
                archive.add(published, arcname="package")
            actual = inspect_tarball(tarball, variant=IMPROVEMENT2_VARIANT)["contentDigest"]
            self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
