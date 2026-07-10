from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from configs.path import PROJECT_ROOT

DEFAULT_CONFIG_PATH = Path(PROJECT_ROOT) / "configs" / "generated-state.json"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class GeneratedStateConfigError(ValueError):
    pass


def _require_string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise GeneratedStateConfigError(f"{field} must be a string")
    text = value.strip()
    if not text:
        raise GeneratedStateConfigError(f"{field} cannot be empty")
    return text


def _normalize_relative_path(value: object, *, field: str) -> str:
    text = _require_string(value, field=field).replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise GeneratedStateConfigError(f"{field} contains an unsafe relative path: {value!r}")
    return path.as_posix()


def _read_paths(payload: dict, field: str) -> tuple[str, ...]:
    values = payload.get(field)
    if not isinstance(values, list) or not values:
        raise GeneratedStateConfigError(f"{field} must be a non-empty array")
    normalized = tuple(_normalize_relative_path(value, field=field) for value in values)
    if len(set(normalized)) != len(normalized):
        raise GeneratedStateConfigError(f"{field} contains duplicate paths")
    return normalized


def _read_patterns(payload: dict, field: str) -> tuple[str, ...]:
    values = payload.get(field, [])
    if not isinstance(values, list):
        raise GeneratedStateConfigError(f"{field} must be an array")
    patterns: list[str] = []
    for value in values:
        pattern = _require_string(value, field=field).replace("\\", "/")
        if pattern.startswith("/") or ".." in PurePosixPath(pattern).parts:
            raise GeneratedStateConfigError(f"unsafe exclude pattern: {pattern!r}")
        patterns.append(pattern)
    if len(set(patterns)) != len(patterns):
        raise GeneratedStateConfigError(f"{field} contains duplicate patterns")
    return tuple(patterns)


def _is_same_or_child(path: str, parent: str) -> bool:
    value = PurePosixPath(path)
    root = PurePosixPath(parent)
    return value == root or root in value.parents


@dataclass(frozen=True)
class GeneratedStateConfig:
    schema_version: int
    state_id: str
    role: str
    backend: str
    ref: str
    management: str
    manifest_path: str
    export_paths: tuple[str, ...]
    baseline_sync_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    exclude_patterns: tuple[str, ...]

    def validate_relative_path(self, path: str, *, require_exported: bool = False) -> str:
        normalized = _normalize_relative_path(path, field="path")
        if any(_is_same_or_child(normalized, forbidden) for forbidden in self.forbidden_paths):
            raise GeneratedStateConfigError(f"path is forbidden for generated-state: {normalized}")
        if require_exported and not any(
            _is_same_or_child(normalized, exported) for exported in self.export_paths
        ):
            raise GeneratedStateConfigError(f"path is outside generated-state export roots: {normalized}")
        return normalized

    def validate(self) -> None:
        if self.schema_version != 1:
            raise GeneratedStateConfigError(
                f"unsupported generated-state config schema: {self.schema_version}"
            )
        if not _ID_RE.fullmatch(self.state_id):
            raise GeneratedStateConfigError(f"invalid generated-state id: {self.state_id!r}")
        if self.role != "generated-state":
            raise GeneratedStateConfigError(f"unexpected generated-state role: {self.role!r}")
        if self.backend != "git-ref":
            raise GeneratedStateConfigError(
                f"Spider currently supports only git-ref generated-state, got {self.backend!r}"
            )
        if self.management != "project-managed":
            raise GeneratedStateConfigError(
                f"generated-state must be project-managed, got {self.management!r}"
            )
        if any(char.isspace() for char in self.ref) or any(
            token in self.ref for token in ("..", "~", "^", ":", "?", "*", "[", "\\")
        ):
            raise GeneratedStateConfigError(f"unsafe generated-state ref: {self.ref!r}")
        manifest_path = _normalize_relative_path(self.manifest_path, field="manifestPath")
        if not _is_same_or_child(manifest_path, ".generated-state"):
            raise GeneratedStateConfigError(
                "manifestPath must be stored under .generated-state/"
            )
        for path in self.export_paths:
            self.validate_relative_path(path)
        for path in self.baseline_sync_paths:
            self.validate_relative_path(path, require_exported=True)
        for field, paths in (
            ("exportPaths", self.export_paths),
            ("baselineSyncPaths", self.baseline_sync_paths),
        ):
            for left_index, left in enumerate(paths):
                for right in paths[left_index + 1 :]:
                    if _is_same_or_child(left, right) or _is_same_or_child(right, left):
                        raise GeneratedStateConfigError(
                            f"{field} must not overlap: {left!r} and {right!r}"
                        )


def load_generated_state_config(path: Path | None = None) -> GeneratedStateConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise GeneratedStateConfigError("generated-state config must be a JSON object")
    config = GeneratedStateConfig(
        schema_version=int(payload.get("schemaVersion", 0)),
        state_id=_require_string(payload.get("id"), field="id"),
        role=_require_string(payload.get("role"), field="role"),
        backend=_require_string(payload.get("backend"), field="backend"),
        ref=_require_string(payload.get("ref"), field="ref"),
        management=_require_string(payload.get("management"), field="management"),
        manifest_path=_normalize_relative_path(payload.get("manifestPath"), field="manifestPath"),
        export_paths=_read_paths(payload, "exportPaths"),
        baseline_sync_paths=_read_paths(payload, "baselineSyncPaths"),
        forbidden_paths=_read_paths(payload, "forbiddenPaths"),
        exclude_patterns=_read_patterns(payload, "excludePatterns"),
    )
    config.validate()
    return config
