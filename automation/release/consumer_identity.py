from __future__ import annotations

"""Deterministic consumer-data identities for npm release reconciliation.

The canonical and ``improvement2`` packages expose different improvement-detail
schemas, so they intentionally have separate digests.  Both digests are derived
from the actual consumer files, never from version metadata or a previous
workflow receipt.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
from typing import Iterable, Iterator

from automation.common.process import AutomationError

ProjectCommandError = AutomationError

IDENTITY_SCHEMA_VERSION = 3
CURRENT_VARIANT = "current"
IMPROVEMENT2_VARIANT = "improvement2"
IMPROVEMENT2_CONSUMER = "poi-plugin-item-improvement2"
_VARIANTS = {CURRENT_VARIANT, IMPROVEMENT2_VARIANT}
_CURRENT_DATA_PREFIXES = (
    "improvement/",
    "equipment/",
    "assets/equip/",
    "assets/useitem/",
)
_IMPROVEMENT2_DATA_PREFIXES = (
    "improvement/",
    "assets/useitem/",
)


def _canonical_json_bytes(raw: bytes, *, label: str) -> bytes:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectCommandError(f"consumer JSON is invalid: {label}: {exc}") from exc
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
        raise ProjectCommandError(f"consumer JSONL is not UTF-8: {label}: {exc}") from exc
    lines: list[bytes] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProjectCommandError(
                f"consumer JSONL is invalid: {label}:{line_number}: {exc}"
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


def _wanted(relative: str, *, variant: str) -> bool:
    prefixes = (
        _IMPROVEMENT2_DATA_PREFIXES
        if variant == IMPROVEMENT2_VARIANT
        else _CURRENT_DATA_PREFIXES
    )
    return relative.startswith(prefixes)


def _digest_records(variant: str, records: Iterable[tuple[str, bytes]]) -> dict:
    if variant not in _VARIANTS:
        raise ProjectCommandError(f"unsupported consumer identity variant: {variant}")
    digest = hashlib.sha256()
    digest.update(f"kancolle-data-consumer-identity-v{IDENTITY_SCHEMA_VERSION}\0".encode("ascii"))
    digest.update(variant.encode("ascii"))
    digest.update(b"\0")
    files: dict[str, dict[str, object]] = {}
    seen: set[str] = set()
    for relative, raw in sorted(records, key=lambda item: item[0]):
        if relative in seen:
            raise ProjectCommandError(f"duplicate consumer identity path: {relative}")
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
        raise ProjectCommandError("consumer identity contains no data files")
    return {
        "schemaVersion": IDENTITY_SCHEMA_VERSION,
        "variant": variant,
        "contentDigest": digest.hexdigest(),
        "fileCount": len(files),
        "files": files,
    }


def _directory_records(
    package_dir: Path,
    *,
    variant: str,
    source_projection: bool,
) -> Iterator[tuple[str, bytes]]:
    package_dir = package_dir.resolve()
    if variant == IMPROVEMENT2_VARIANT and source_projection:
        compat_root = package_dir / "compat" / IMPROVEMENT2_CONSUMER
        for root_name in ("improvement", "assets/useitem"):
            root = compat_root / root_name
            if not root.is_dir():
                raise ProjectCommandError(
                    f"improvement2 compatibility projection is missing: {root}"
                )
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                relative = f"{root_name}/{path.relative_to(root).as_posix()}"
                if _wanted(relative, variant=variant):
                    yield relative, path.read_bytes()
        return

    roots = (
        ("improvement", "assets/useitem")
        if variant == IMPROVEMENT2_VARIANT
        else ("improvement", "equipment", "assets/equip", "assets/useitem")
    )
    for root_name in roots:
        root = package_dir / root_name
        if not root.is_dir():
            raise ProjectCommandError(f"consumer data directory is missing: {root}")
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(package_dir).as_posix()
            if _wanted(relative, variant=variant):
                yield relative, path.read_bytes()


def inspect_directory(
    package_dir: Path,
    *,
    variant: str,
    source_projection: bool = False,
) -> dict:
    return _digest_records(
        variant,
        _directory_records(
            package_dir,
            variant=variant,
            source_projection=source_projection,
        ),
    )


def _safe_member_relative(name: str, *, variant: str) -> str | None:
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts:
        raise ProjectCommandError(f"unsafe npm tarball member: {name}")
    if not pure.parts or pure.parts[0] != "package":
        return None
    relative = PurePosixPath(*pure.parts[1:]).as_posix()
    return relative if _wanted(relative, variant=variant) else None


def _tarball_records(tarball: Path, *, variant: str) -> Iterator[tuple[str, bytes]]:
    tarball = tarball.resolve()
    if not tarball.is_file() or tarball.is_symlink():
        raise ProjectCommandError(f"npm tarball is missing or unsafe: {tarball}")
    with tarfile.open(tarball, "r:gz") as archive:
        for member in sorted(archive.getmembers(), key=lambda item: item.name):
            relative = _safe_member_relative(member.name, variant=variant)
            if relative is None:
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise ProjectCommandError(
                    f"consumer npm tarball member is not a regular file: {member.name}"
                )
            stream = archive.extractfile(member)
            if stream is None:
                raise ProjectCommandError(f"npm tarball member cannot be read: {member.name}")
            yield relative, stream.read()


def inspect_tarball(tarball: Path, *, variant: str) -> dict:
    return _digest_records(variant, _tarball_records(tarball, variant=variant))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compute deterministic consumer-data identities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    directory = subparsers.add_parser("directory")
    directory.add_argument("--package-dir", required=True, type=Path)
    directory.add_argument("--variant", required=True, choices=sorted(_VARIANTS))
    directory.add_argument("--source-projection", action="store_true")

    tarball = subparsers.add_parser("tarball")
    tarball.add_argument("--tarball", required=True, type=Path)
    tarball.add_argument("--variant", required=True, choices=sorted(_VARIANTS))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "directory":
        result = inspect_directory(
            args.package_dir,
            variant=args.variant,
            source_projection=bool(args.source_projection),
        )
    else:
        result = inspect_tarball(args.tarball, variant=args.variant)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
