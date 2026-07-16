from __future__ import annotations

"""Resolve one immutable Source Bundle artifact for a Build workflow.

The resolver is intentionally stateless.  It either selects the explicitly
requested successful Acquire run or the latest completed+successful Acquire
run, then freezes the exact artifact identity returned by GitHub.  Active and
failed Acquire runs never block an existing successful bundle.
"""

import argparse
import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

WORKFLOW_PATH = ".github/workflows/source-acquire.yml"
WORKFLOW_NAME = "source-acquire.yml"
ARTIFACT_NAME = "kancolle-source-bundle"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class SourceResolutionError(RuntimeError):
    pass


JsonLoader = Callable[[str], dict[str, Any]]


def github_json_loader(*, token: str) -> JsonLoader:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    def load(url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise SourceResolutionError("GitHub API returned a non-object payload")
        return payload

    return load


def _positive_int(value: object, *, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise SourceResolutionError(f"{label} is invalid") from exc
    if result <= 0:
        raise SourceResolutionError(f"{label} is invalid")
    return result


def _validate_run(run: dict[str, Any], *, requested: bool) -> dict[str, Any]:
    label = "requested" if requested else "selected"
    path = str(run.get("path") or "").split("@", 1)[0]
    if path != WORKFLOW_PATH or run.get("head_branch") != "main":
        raise SourceResolutionError(
            f"{label} source run is not {WORKFLOW_NAME} on main"
        )
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise SourceResolutionError(f"{label} source run is not completed + success")
    _positive_int(run.get("id"), label=f"{label} source run ID")
    _positive_int(run.get("run_attempt") or 1, label=f"{label} source run attempt")
    head_sha = str(run.get("head_sha") or "").lower()
    if not _COMMIT_RE.fullmatch(head_sha):
        raise SourceResolutionError(f"{label} source run head SHA is invalid")
    return run


def _requested_run(
    *, api_root: str, run_id: str, load_json: JsonLoader
) -> dict[str, Any]:
    try:
        normalized = str(_positive_int(run_id, label="requested source run ID"))
    except SourceResolutionError:
        raise
    return _validate_run(
        load_json(f"{api_root}/actions/runs/{urllib.parse.quote(normalized)}"),
        requested=True,
    )


def _latest_successful_run(
    *, api_root: str, load_json: JsonLoader, max_pages: int = 10
) -> dict[str, Any] | None:
    for page in range(1, max_pages + 1):
        query = urllib.parse.urlencode(
            {
                "branch": "main",
                "status": "completed",
                "per_page": 100,
                "page": page,
            }
        )
        payload = load_json(
            f"{api_root}/actions/workflows/{WORKFLOW_NAME}/runs?{query}"
        )
        runs = payload.get("workflow_runs") or []
        if not isinstance(runs, list):
            raise SourceResolutionError("GitHub workflow runs payload is invalid")
        for run in runs:
            if isinstance(run, dict) and run.get("conclusion") == "success":
                return _validate_run(run, requested=False)
        if len(runs) < 100:
            break
    return None


def _source_artifact(
    *, api_root: str, run: dict[str, Any], load_json: JsonLoader
) -> dict[str, Any]:
    run_id = _positive_int(run.get("id"), label="selected source run ID")
    query = urllib.parse.urlencode({"name": ARTIFACT_NAME, "per_page": 100})
    payload = load_json(f"{api_root}/actions/runs/{run_id}/artifacts?{query}")
    artifacts = payload.get("artifacts") or []
    if not isinstance(artifacts, list):
        raise SourceResolutionError("GitHub artifacts payload is invalid")
    candidates = [
        item
        for item in artifacts
        if isinstance(item, dict)
        and item.get("name") == ARTIFACT_NAME
        and item.get("expired") is False
    ]
    if not candidates:
        raise SourceResolutionError(
            f"selected successful source run {run_id} has no usable {ARTIFACT_NAME} artifact"
        )
    candidates.sort(
        key=lambda item: (
            str(item.get("created_at") or ""),
            int(item.get("id") or 0),
        ),
        reverse=True,
    )
    artifact = candidates[0]
    artifact_id = _positive_int(artifact.get("id"), label="source artifact ID")
    digest = str(artifact.get("digest") or "").lower()
    if not _SHA256_RE.fullmatch(digest):
        raise SourceResolutionError(
            f"selected source artifact {artifact_id} lacks an immutable sha256 digest"
        )
    workflow_run = artifact.get("workflow_run") or {}
    if not isinstance(workflow_run, dict):
        raise SourceResolutionError("selected source artifact workflow binding is invalid")
    if _positive_int(workflow_run.get("id"), label="artifact workflow run ID") != run_id:
        raise SourceResolutionError("selected source artifact workflow binding is inconsistent")
    artifact_head = str(workflow_run.get("head_sha") or "").lower()
    run_head = str(run.get("head_sha") or "").lower()
    if artifact_head and artifact_head != run_head:
        raise SourceResolutionError("selected source artifact head SHA is inconsistent")
    return artifact


def resolve_source(
    *,
    repository: str,
    requested_run_id: str = "",
    load_json: JsonLoader,
) -> dict[str, str]:
    if not repository or "/" not in repository:
        raise SourceResolutionError("GitHub repository identity is invalid")
    api_root = f"https://api.github.com/repos/{repository}"
    requested = requested_run_id.strip()
    selected = (
        _requested_run(api_root=api_root, run_id=requested, load_json=load_json)
        if requested
        else _latest_successful_run(api_root=api_root, load_json=load_json)
    )
    if selected is None:
        return {
            "run_id": "",
            "run_attempt": "",
            "artifact_id": "",
            "artifact_name": "",
            "artifact_digest": "",
            "source_head_sha": "",
            "skip": "true",
            "reason": "no-successful-source-acquire",
        }

    artifact = _source_artifact(api_root=api_root, run=selected, load_json=load_json)
    return {
        "run_id": str(_positive_int(selected.get("id"), label="source run ID")),
        "run_attempt": str(
            _positive_int(selected.get("run_attempt") or 1, label="source run attempt")
        ),
        "artifact_id": str(_positive_int(artifact.get("id"), label="source artifact ID")),
        "artifact_name": ARTIFACT_NAME,
        "artifact_digest": str(artifact.get("digest") or "").lower(),
        "source_head_sha": str(selected.get("head_sha") or "").lower(),
        "skip": "false",
        "reason": "ready",
    }


def write_github_output(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as output:
        for key, value in values.items():
            if "\n" in key or "\n" in value:
                raise SourceResolutionError("GitHub output contains an invalid newline")
            output.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve one immutable successful Source Bundle artifact"
    )
    parser.add_argument("--repository", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--source-run-id", default="")
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()
    values = resolve_source(
        repository=args.repository,
        requested_run_id=args.source_run_id,
        load_json=github_json_loader(token=args.token),
    )
    write_github_output(args.github_output, values)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
