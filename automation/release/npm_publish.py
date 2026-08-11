from __future__ import annotations

import argparse
import json
from pathlib import Path

from automation.release.npm_registry import reconcile_npm_publish
from automation.release.npm_release_set import verify_release_set


def publish_release_set(manifest_path: Path, audit_dir: Path) -> dict:
    manifest_path = manifest_path.resolve()
    payload = verify_release_set(manifest_path)
    audit_dir = audit_dir.resolve()
    audit_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for artifact in payload["artifacts"]:
        package_result = manifest_path.parent / str(artifact["packageResult"])
        audit = reconcile_npm_publish(
            package_result_path=package_result,
            audit_output=audit_dir / f"{artifact['variant']}.publish-audit.json",
            tag=str(artifact["distTag"]),
            publish=True,
        )
        results.append(audit)
    return {"schemaVersion": 1, "package": payload["package"], "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Idempotently publish a frozen npm release-set")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--audit-dir", type=Path, required=True)
    args = parser.parse_args()
    result = publish_release_set(args.manifest, args.audit_dir)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
