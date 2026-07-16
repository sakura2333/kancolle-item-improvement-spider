from __future__ import annotations

"""Deterministic business identity for the actual npm package payload.

The identity is computed from the files that npm really packed, not from Flow,
Git, a previous workflow receipt, or RELEASES.json self-reported digests.  It is
used only by the Spider data-publication workflow to decide whether the
``kancolle-data`` npm package changed.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
from typing import Iterable, Iterator

from automation.common.process import AutomationError

ProjectCommandError = AutomationError

IDENTITY_SCHEMA_VERSION = 1

# These files are intentionally not part of the npm business-change decision.
# They are documentation, release history, generated diagnostics, or a derived
# runtime manifest whose volatile acquisition evidence must not allocate a new
# npm version by itself.
_EXCLUDED_FILES = {
    "CHANGELOG.md",
    "LICENSES.md",
    "README.md",
    "RELEASES.json",
    "manifest.json",
}
_EXCLUDED_PREFIXES = ("audit/",)
_PACKAGE_JSON_VOLATILE_KEYS = {"version"}


def _canonical_json_bytes(raw: bytes, *, label: str) -> bytes:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectCommandError(f"npm business JSON is invalid: {label}: {exc}") from exc
    if label == "package.json":
        if not isinstance(value, dict):
            raise ProjectCommandError("npm package.json must contain an object")
        value = {
            key: item
            for key, item in value.items()
            if key not in _PACKAGE_JSON_VOLATILE_KEYS
        }
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"


def _canonical_json_lines(raw: bytes, *, label: str) -> bytes:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectCommandError(f"npm business JSONL is not UTF-8: {label}: {exc}") from exc
    lines: list[bytes] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProjectCommandError(
                f"npm business JSONL is invalid: {label}:{line_number}: {exc}"
            ) from exc
        lines.append(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    return b"\n".join(lines) + (b"\n" if lines else b"")


def _normalized_bytes(relative: str, raw: bytes) -> bytes:
    if relative.endswith(".json"):
        return _canonical_json_bytes(raw, label=relative)
    if relative.endswith(".nedb"):
        return _canonical_json_lines(raw, label=relative)
    return raw


def _wanted(relative: str) -> bool:
    return relative not in _EXCLUDED_FILES and not relative.startswith(_EXCLUDED_PREFIXES)


def _digest_records(records: Iterable[tuple[str, bytes]]) -> dict:
    digest = hashlib.sha256()
    digest.update(
        f"kancolle-data-npm-business-identity-v{IDENTITY_SCHEMA_VERSION}\0".encode("ascii")
    )
    files: dict[str, dict[str, object]] = {}
    seen: set[str] = set()
    for relative, raw in sorted(records, key=lambda item: item[0]):
        if relative in seen:
            raise ProjectCommandError(f"duplicate npm business identity path: {relative}")
        seen.add(relative)
        normalized = _normalized_bytes(relative, raw)
        file_digest = hashlib.sha256(normalized).hexdigest()
        files[relative] = {
            "bytes": len(raw),
            "normalizedBytes": len(normalized),
            "sha256": file_digest,
        }
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\n")
    if not files:
        raise ProjectCommandError("npm business identity contains no package files")
    if "package.json" not in files:
        raise ProjectCommandError("npm business identity lacks package.json")
    return {
        "schemaVersion": IDENTITY_SCHEMA_VERSION,
        "businessDigest": digest.hexdigest(),
        "fileCount": len(files),
        "files": files,
    }


def _safe_member_relative(name: str) -> str | None:
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts:
        raise ProjectCommandError(f"unsafe npm tarball member: {name}")
    if not pure.parts or pure.parts[0] != "package":
        return None
    relative = PurePosixPath(*pure.parts[1:]).as_posix()
    if not relative or not _wanted(relative):
        return None
    return relative


def _tarball_records(tarball: Path) -> Iterator[tuple[str, bytes]]:
    tarball = tarball.resolve()
    if not tarball.is_file() or tarball.is_symlink():
        raise ProjectCommandError(f"npm tarball is missing or unsafe: {tarball}")
    with tarfile.open(tarball, "r:gz") as archive:
        for member in sorted(archive.getmembers(), key=lambda item: item.name):
            if member.isdir():
                continue
            relative = _safe_member_relative(member.name)
            if relative is None:
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise ProjectCommandError(
                    f"npm business tarball member is not a regular file: {member.name}"
                )
            stream = archive.extractfile(member)
            if stream is None:
                raise ProjectCommandError(f"npm tarball member cannot be read: {member.name}")
            yield relative, stream.read()


def inspect_tarball(tarball: Path) -> dict:
    return _digest_records(_tarball_records(tarball))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compute the normalized business identity of an npm tarball"
    )
    parser.add_argument("--tarball", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = inspect_tarball(args.tarball)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
