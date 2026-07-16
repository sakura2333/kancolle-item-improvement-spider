from __future__ import annotations

"""Project file ownership and code-only content identity.

Generated data is a separately managed state.  It is intentionally excluded
from code update packages, code candidate identity and ``push`` staging.
"""

import fnmatch
import hashlib
import subprocess
from functools import lru_cache
from pathlib import Path

from service.generated_state.config import load_generated_state_config

CONTENT_IDENTITY_EXCLUDED = (
    ".flow/baseline.json",
)

LOCAL_PRESERVED = (
    ".git/**",
    ".flow/local.json",
    ".flow/local/**",
    ".flow/packages/**",
    ".flow/state/**",
    "configs/local/**",
    "configs/*.local.*",
    "configs/**/*.local.*",
    "configs/*.private.*",
    "configs/**/*.private.*",
    "configs/*.secret.*",
    "configs/**/*.secret.*",
    ".venv/**",
    ".idea/**",
    "log/**",
    "dist/**",
    "data/raw_data/**",
)


def _matches(value: str, pattern: str) -> bool:
    value = value.replace("\\", "/").strip("/")
    pattern = pattern.replace("\\", "/").strip("/")
    base = pattern[:-3] if pattern.endswith("/**") else pattern
    return value == base or value.startswith(base + "/") or fnmatch.fnmatch(value, pattern)


@lru_cache(maxsize=None)
def _generated_patterns_cached(config_path: str, mtime_ns: int, size: int) -> tuple[str, ...]:
    config = load_generated_state_config(Path(config_path))
    return tuple(path if path.endswith("/**") else f"{path}/**" for path in config.export_paths)


def generated_patterns(root: Path) -> tuple[str, ...]:
    config_path = root / "configs/generated-state.json"
    stat = config_path.stat()
    return _generated_patterns_cached(str(config_path.resolve()), stat.st_mtime_ns, stat.st_size)


def classify_path(root: Path, relative: str) -> str:
    value = relative.replace("\\", "/").strip("/")
    if any(_matches(value, pattern) for pattern in LOCAL_PRESERVED):
        return "local-preserved"
    if any(_matches(value, pattern) for pattern in generated_patterns(root)):
        return "generated-state"
    return "project-owned"


def split_paths(root: Path, paths: list[str]) -> dict[str, list[str]]:
    result = {"project-owned": [], "generated-state": [], "local-preserved": []}
    for path in paths:
        result[classify_path(root, path)].append(path)
    for values in result.values():
        values.sort()
    return result


def update_protected_patterns(root: Path) -> list[str]:
    return [*LOCAL_PRESERVED, *generated_patterns(root)]


def update_policy(root: Path) -> dict:
    return {
        "maxFileBytes": 20_000_000,
        "requiredBranch": "dev",
        "protected": update_protected_patterns(root),
        "identityProvider": "script.project.ownership:identity_value",
        "autoCommit": True,
        "autoCommitRollback": True,
        "commitMessageTemplate": "更新 {projectId} {fromVersion} → {toVersion}",
        "candidateVerifier": [
            "{python}", "script/project/python_runner.py", "script/project/cli.py",
            "verify-candidate", "--json",
        ],
    }


def recovery_policy() -> dict:
    generated = load_generated_state_config(
        Path(__file__).resolve().parents[2] / "configs/generated-state.json"
    )
    return {
        "includeLocal": [".flow/local.json", ".idea", "data/raw_data"],
        "includeGeneratedState": list(generated.export_paths),
        "exclude": [".venv", "log", "dist", ".flow/state", "**/__pycache__", "**/*.pyc"],
    }


def candidate_paths_for_identity(root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    values = []
    for raw in completed.stdout.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8")
        if relative in CONTENT_IDENTITY_EXCLUDED:
            continue
        if classify_path(root, relative) == "project-owned":
            values.append(relative)
    return sorted(set(values))


def project_owned_identity(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in candidate_paths_for_identity(root):
        path = root / relative
        if not path.exists():
            continue
        if path.is_symlink():
            raise RuntimeError(f"project-owned identity does not allow symlinks: {relative}")
        if not path.is_file():
            continue
        mode = "100755" if path.stat().st_mode & 0o111 else "100644"
        file_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(mode.encode("ascii"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def identity_value(root: Path, scheme: str) -> str:
    if scheme not in {"project-owned-sha256", "flow-content-sha256"}:
        raise RuntimeError(f"unsupported project identity scheme: {scheme}")
    return project_owned_identity(root)


def git_dirty_paths(root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    entries = [item for item in completed.stdout.split(b"\0") if item]
    paths: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index].decode("utf-8")
        status = entry[:2]
        path = entry[3:]
        paths.append(path)
        if status[0] in {"R", "C"} and index + 1 < len(entries):
            index += 1
            paths.append(entries[index].decode("utf-8"))
        index += 1
    return sorted(set(paths))
