from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import tarfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlparse

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_COMMIT_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


class NpmPublishError(RuntimeError):
    pass


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity_sha512(path: Path) -> str:
    digest = hashlib.sha512()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha512-" + base64.b64encode(digest.digest()).decode("ascii")


def _default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(item) for item in command],
        check=False,
        text=True,
        capture_output=True,
    )


def _command_error(completed: subprocess.CompletedProcess[str], fallback: str) -> str:
    return (completed.stderr or completed.stdout or fallback).strip()


def _run_checked(runner: CommandRunner, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    completed = runner(command)
    if completed.returncode != 0:
        raise NpmPublishError(_command_error(completed, "npm command failed"))
    return completed


def _validate_tag(tag: str) -> str:
    value = tag.strip()
    if not _TAG_RE.fullmatch(value):
        raise NpmPublishError(f"invalid npm dist-tag: {tag!r}")
    return value


def resolve_registry(
    registry: str | None,
    *,
    runner: CommandRunner = _default_runner,
) -> str:
    if registry:
        value = registry.strip()
    else:
        completed = _run_checked(runner, ["npm", "config", "get", "registry"])
        value = completed.stdout.strip()
    if not value or value == "undefined":
        raise NpmPublishError("npm registry is not configured")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise NpmPublishError(f"unsupported npm registry URL: {value!r}")
    return value.rstrip("/") + "/"


def load_package_result(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpmPublishError(f"cannot read package result: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise NpmPublishError("unsupported package result schema")
    for field in ("package", "version", "tarball", "sha256"):
        if not str(payload.get(field, "")).strip():
            raise NpmPublishError(f"package result is missing {field}")
    expected_sha256 = str(payload["sha256"]).lower()
    if not _SHA256_RE.fullmatch(expected_sha256):
        raise NpmPublishError("package result contains an invalid sha256")
    tarball = Path(str(payload["tarball"])).expanduser().resolve()
    if not tarball.is_file() or tarball.is_symlink():
        raise NpmPublishError(f"tarball does not exist or is not regular: {tarball}")
    actual_sha256 = _digest(tarball, "sha256")
    if actual_sha256 != expected_sha256:
        raise NpmPublishError("tarball sha256 does not match package result")

    try:
        with tarfile.open(tarball, "r:gz") as archive:
            member = archive.getmember("package/package.json")
            if not member.isfile() or member.size > 1024 * 1024:
                raise NpmPublishError("tarball package.json is not a small regular file")
            stream = archive.extractfile(member)
            if stream is None:
                raise NpmPublishError("tarball package.json cannot be read")
            package_json = json.loads(stream.read().decode("utf-8"))
    except (KeyError, tarfile.TarError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise NpmPublishError(f"invalid npm tarball: {exc}") from exc

    if str(package_json.get("name")) != str(payload["package"]):
        raise NpmPublishError("tarball package name does not match package result")
    if str(package_json.get("version")) != str(payload["version"]):
        raise NpmPublishError("tarball version does not match package result")
    return {**payload, "sha256": expected_sha256, "tarball": str(tarball)}


def _is_not_found(completed: subprocess.CompletedProcess[str]) -> bool:
    text = f"{completed.stdout}\n{completed.stderr}"
    return completed.returncode != 0 and ("E404" in text or "404 Not Found" in text)


def query_registry_release(
    package: str,
    version: str,
    *,
    registry: str,
    runner: CommandRunner = _default_runner,
) -> dict[str, Any] | None:
    spec = f"{package}@{version}"
    completed = runner(["npm", "view", spec, "dist", "--json", "--registry", registry])
    if _is_not_found(completed):
        return None
    if completed.returncode != 0:
        raise NpmPublishError(_command_error(completed, "npm view failed"))
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise NpmPublishError(f"npm view returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise NpmPublishError("npm view dist result must be a JSON object")
    return {
        "package": package,
        "version": version,
        "registry": registry,
        "shasum": payload.get("shasum"),
        "integrity": payload.get("integrity"),
        "tarball": payload.get("tarball"),
    }


def query_dist_tags(
    package: str,
    *,
    registry: str,
    runner: CommandRunner = _default_runner,
) -> dict[str, str]:
    completed = runner(
        ["npm", "view", package, "dist-tags", "--json", "--registry", registry]
    )
    if _is_not_found(completed):
        return {}
    if completed.returncode != 0:
        raise NpmPublishError(_command_error(completed, "npm dist-tag query failed"))
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise NpmPublishError(f"npm dist-tag query returned invalid JSON: {exc}") from exc
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise NpmPublishError("npm dist-tags result must be a JSON object")
    return {str(key): str(value) for key, value in payload.items()}


def compare_registry_release(tarball: Path, remote: dict[str, Any]) -> dict[str, Any]:
    local_sha1 = _digest(tarball, "sha1")
    local_integrity = _integrity_sha512(tarball)
    remote_sha1 = str(remote.get("shasum") or "")
    remote_integrity = str(remote.get("integrity") or "")
    if not remote_sha1 and not remote_integrity:
        raise NpmPublishError("registry release has neither shasum nor integrity")
    sha1_matches = not remote_sha1 or remote_sha1 == local_sha1
    integrity_matches = not remote_integrity or remote_integrity == local_integrity
    return {
        "matches": sha1_matches and integrity_matches,
        "localSha1": local_sha1,
        "remoteSha1": remote_sha1 or None,
        "localIntegrity": local_integrity,
        "remoteIntegrity": remote_integrity or None,
    }


def _provenance(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpmPublishError(f"cannot read provenance manifest: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise NpmPublishError("unsupported provenance manifest")
    build_id = str(payload.get("buildId", "")).strip()
    base_revision = payload.get("baseRevision")
    if not build_id or not isinstance(base_revision, dict):
        raise NpmPublishError("provenance manifest is missing buildId or baseRevision")
    commit = str(base_revision.get("commit", ""))
    if base_revision.get("type") != "git" or not _COMMIT_RE.fullmatch(commit):
        raise NpmPublishError("provenance manifest has an invalid Git base revision")
    return {
        "buildId": build_id,
        "baseRevision": base_revision,
        "manifest": str(path.resolve()),
        "manifestSha256": _digest(path, "sha256"),
    }


def write_audit(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _poll_release(
    *,
    package: str,
    version: str,
    registry: str,
    retries: int,
    retry_delay: float,
    runner: CommandRunner,
) -> tuple[dict[str, Any] | None, str | None]:
    last_error: str | None = None
    for attempt in range(max(1, retries)):
        try:
            release = query_registry_release(
                package,
                version,
                registry=registry,
                runner=runner,
            )
            if release is not None:
                return release, None
            last_error = None
        except NpmPublishError as exc:
            last_error = str(exc)
        if attempt + 1 < max(1, retries):
            time.sleep(max(0.0, retry_delay))
    return None, last_error


def _ensure_dist_tag(
    *,
    package: str,
    version: str,
    tag: str,
    registry: str,
    mutate: bool,
    runner: CommandRunner,
) -> dict[str, Any]:
    before = query_dist_tags(package, registry=registry, runner=runner)
    if before.get(tag) == version:
        return {"tag": tag, "before": before.get(tag), "after": version, "changed": False}
    if not mutate:
        return {
            "tag": tag,
            "before": before.get(tag),
            "after": before.get(tag),
            "changed": False,
            "matches": False,
        }

    command = [
        "npm",
        "dist-tag",
        "add",
        f"{package}@{version}",
        tag,
        "--registry",
        registry,
    ]
    completed = runner(command)
    after = query_dist_tags(package, registry=registry, runner=runner)
    if after.get(tag) == version:
        return {
            "tag": tag,
            "before": before.get(tag),
            "after": version,
            "changed": before.get(tag) != version,
            "commandReturnCode": completed.returncode,
        }
    if completed.returncode != 0:
        raise NpmPublishError(_command_error(completed, "npm dist-tag add failed"))
    raise NpmPublishError(f"npm dist-tag {tag!r} was not updated to {version}")


def reconcile_npm_publish(
    *,
    package_result_path: Path,
    audit_output: Path,
    tag: str,
    registry: str | None = None,
    publish: bool = False,
    provenance_manifest: Path | None = None,
    retries: int = 5,
    retry_delay: float = 2.0,
    runner: CommandRunner = _default_runner,
) -> dict[str, Any]:
    package_result = load_package_result(package_result_path)
    tarball = Path(str(package_result["tarball"]))
    normalized_tag = _validate_tag(tag)
    attempt_id = str(uuid.uuid4())
    audit: dict[str, Any] = {
        "schemaVersion": 1,
        "attemptId": attempt_id,
        "checkedAt": _utc_now(),
        "package": package_result["package"],
        "version": package_result["version"],
        "tag": normalized_tag,
        "registry": registry,
        "tarball": {
            "path": str(tarball),
            "sha256": package_result["sha256"],
            "sha1": _digest(tarball, "sha1"),
            "integrity": _integrity_sha512(tarball),
            "bytes": tarball.stat().st_size,
        },
        "provenance": _provenance(provenance_manifest),
        "publishRequested": publish,
    }

    try:
        resolved_registry = resolve_registry(registry, runner=runner)
        audit["registry"] = resolved_registry
        package = str(package_result["package"])
        version = str(package_result["version"])
        remote = query_registry_release(
            package,
            version,
            registry=resolved_registry,
            runner=runner,
        )
        if remote is not None:
            comparison = compare_registry_release(tarball, remote)
            audit.update({"registryRelease": remote, "comparison": comparison})
            if not comparison["matches"]:
                audit["status"] = "immutable-version-conflict"
                write_audit(audit_output, audit)
                raise NpmPublishError(
                    "npm version already exists with different tarball content"
                )
            tag_result = _ensure_dist_tag(
                package=package,
                version=version,
                tag=normalized_tag,
                registry=resolved_registry,
                mutate=publish,
                runner=runner,
            )
            audit["distTag"] = tag_result
            if tag_result.get("after") != version:
                audit["status"] = "already-published-tag-mismatch"
            elif tag_result.get("changed"):
                audit["status"] = "tag-reconciled"
            else:
                audit["status"] = "already-published"
            audit["reconciledAt"] = _utc_now()
            write_audit(audit_output, audit)
            return audit

        if not publish:
            audit["status"] = "ready-not-published"
            write_audit(audit_output, audit)
            return audit

        command = [
            "npm",
            "publish",
            str(tarball),
            "--access",
            "public",
            "--tag",
            normalized_tag,
            "--registry",
            resolved_registry,
        ]
        completed = runner(command)
        audit["publishAttempt"] = {
            "attemptedAt": _utc_now(),
            "returnCode": completed.returncode,
            "message": _command_error(completed, "")[:2000] or None,
        }

        remote, poll_error = _poll_release(
            package=package,
            version=version,
            registry=resolved_registry,
            retries=retries,
            retry_delay=retry_delay,
            runner=runner,
        )
        if remote is None:
            audit["status"] = (
                "publish-unconfirmed" if completed.returncode == 0 else "publish-failed"
            )
            if poll_error:
                audit["registryQueryError"] = poll_error
            audit["error"] = _command_error(
                completed,
                "npm publish completed but registry did not confirm the version",
            )
            write_audit(audit_output, audit)
            raise NpmPublishError(str(audit["error"]))

        comparison = compare_registry_release(tarball, remote)
        audit.update({"registryRelease": remote, "comparison": comparison})
        if not comparison["matches"]:
            audit["status"] = "published-content-mismatch"
            write_audit(audit_output, audit)
            raise NpmPublishError("registry content does not match the published tarball")

        tag_result = _ensure_dist_tag(
            package=package,
            version=version,
            tag=normalized_tag,
            registry=resolved_registry,
            mutate=True,
            runner=runner,
        )
        audit["distTag"] = tag_result
        audit["status"] = (
            "published" if completed.returncode == 0 else "published-reconciled-after-command-error"
        )
        audit["reconciledAt"] = _utc_now()
        write_audit(audit_output, audit)
        return audit
    except Exception as exc:
        if "status" not in audit:
            audit["status"] = "failed"
            audit["error"] = f"{type(exc).__name__}: {exc}"
            write_audit(audit_output, audit)
        raise
