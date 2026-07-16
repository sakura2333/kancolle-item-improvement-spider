from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class VersionPlanError(ValueError):
    pass


def parse_version(value: str) -> tuple[int, int, int]:
    match = _SEMVER_RE.fullmatch(value.strip())
    if not match:
        raise VersionPlanError(f"unsupported semantic version: {value!r}")
    return tuple(int(part) for part in match.groups())


def format_version(value: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in value)


def bump_version(version: str, part: str) -> str:
    major, minor, patch = parse_version(version)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise VersionPlanError(f"unsupported version bump: {part!r}")


def normalize_published_versions(values: Iterable[str]) -> list[str]:
    parsed: dict[tuple[int, int, int], str] = {}
    for raw in values:
        value = str(raw).strip()
        if not value or not _SEMVER_RE.fullmatch(value):
            continue
        parsed[parse_version(value)] = value
    return [parsed[key] for key in sorted(parsed)]


@dataclass(frozen=True)
class VersionPlan:
    should_publish: bool
    version: str | None
    reason: str

    def to_json(self) -> dict:
        return {
            "shouldPublish": self.should_publish,
            "version": self.version,
            "reason": self.reason,
        }


def _latest(values: Iterable[str]) -> str | None:
    normalized = normalize_published_versions(values)
    return normalized[-1] if normalized else None


def plan_scheduled_version(
    repository_version: str,
    published_versions: Iterable[str],
    *,
    data_changed: bool,
) -> VersionPlan:
    repository_tuple = parse_version(repository_version)
    published = normalize_published_versions(published_versions)
    published_set = set(published)
    latest = _latest(published)
    latest_tuple = parse_version(latest) if latest else None

    if not data_changed:
        if repository_version not in published_set and (
            latest_tuple is None or repository_tuple > latest_tuple
        ):
            return VersionPlan(True, repository_version, "publish-unpublished-repository-version")
        return VersionPlan(False, None, "consumer-data-unchanged")

    if repository_version not in published_set and (
        latest_tuple is None or repository_tuple > latest_tuple
    ):
        return VersionPlan(True, repository_version, "publish-planned-repository-version")

    base_tuple = repository_tuple
    if latest_tuple is not None and latest_tuple > base_tuple:
        base_tuple = latest_tuple
    return VersionPlan(True, bump_version(format_version(base_tuple), "patch"), "publish-data-change")


def plan_manual_version(
    repository_version: str,
    published_versions: Iterable[str],
    *,
    bump: str,
) -> VersionPlan:
    repository_tuple = parse_version(repository_version)
    published = normalize_published_versions(published_versions)
    published_set = set(published)
    latest = _latest(published)
    latest_tuple = parse_version(latest) if latest else None

    if bump == "none":
        if repository_version in published_set:
            raise VersionPlanError(
                f"repository version {repository_version} is already published; choose a version bump"
            )
        if latest_tuple is not None and repository_tuple <= latest_tuple:
            raise VersionPlanError(
                f"repository version {repository_version} is not newer than published {latest}; choose a version bump"
            )
        return VersionPlan(True, repository_version, "publish-explicit-repository-version")

    base_tuple = repository_tuple
    if latest_tuple is not None and latest_tuple > base_tuple:
        base_tuple = latest_tuple
    return VersionPlan(True, bump_version(format_version(base_tuple), bump), f"manual-{bump}-release")
