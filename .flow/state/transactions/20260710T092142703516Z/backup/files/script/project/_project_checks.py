from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:  # package import, used by tests
    from ._common import PACKAGE_DIR, PACKAGE_SOURCE_DIR, PROJECT_ROOT, ProjectCommandError, assert_paths_exist, project_env, run
except ImportError:  # direct script execution from script/project
    from _common import PACKAGE_DIR, PACKAGE_SOURCE_DIR, PROJECT_ROOT, ProjectCommandError, assert_paths_exist, project_env, run

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from script.project.ownership import classify_path
try:  # package import, used by tests
    from .config_guard import verify_config_governance
except ImportError:  # direct script execution from script/project
    from config_guard import verify_config_governance

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")

REQUIRED_PATHS = (
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "VERSION",
    PROJECT_ROOT / "requirements.txt",
    PROJECT_ROOT / ".flow" / "project.json",
    PROJECT_ROOT / ".flow" / "local.example.json",
    PROJECT_ROOT / "SPIDER-HARD-RULES.md",
    PROJECT_ROOT / "SPIDER-AUTHORITY-MAP.md",
    PROJECT_ROOT / "docs" / "internal" / "ARCHITECTURE.md",
    PROJECT_ROOT / "docs" / "internal" / "DOCUMENTATION-MAP.md",
    PROJECT_ROOT / "docs" / "internal" / "FLOW-ADAPTER.md",
    PROJECT_ROOT / "docs" / "internal" / "PROJECT-TOOLS.md",
    PROJECT_ROOT / "docs" / "internal" / "UPDATE-TRANSACTION.md",
    PROJECT_ROOT / "docs" / "internal" / "RECOVERY-PACKAGE.md",
    PROJECT_ROOT / "docs" / "public" / "README.md",
    PROJECT_ROOT / "configs" / "README.md",
    PROJECT_ROOT / "configs" / "generated-state.json",
    PROJECT_ROOT / "configs" / "wikiwiki-crawler.default.json",
    PROJECT_ROOT / "service",
    PROJECT_ROOT / "service" / "generated_state" / "artifact.py",
    PROJECT_ROOT / "util",
    PROJECT_ROOT / "pojo",
    PROJECT_ROOT / "configs",
    PROJECT_ROOT / "tests",
    PACKAGE_SOURCE_DIR / "package.json",
    PROJECT_ROOT / "flow",
    PROJECT_ROOT / "script" / "flow_adapter.py",
    PROJECT_ROOT / "script" / "flow" / "cli.py",
    PROJECT_ROOT / "script" / "flow" / "contract.py",
    PROJECT_ROOT / "script" / "flow" / "update.py",
    PROJECT_ROOT / "script" / "flow" / "recovery.py",
    PROJECT_ROOT / "script" / "project" / "cli.py",
    PROJECT_ROOT / "script" / "project" / "ownership.py",
    PROJECT_ROOT / "script" / "project" / "runtime.py",
    PROJECT_ROOT / "script" / "project" / "check.py",
    PROJECT_ROOT / "script" / "project" / "config_guard.py",
    PROJECT_ROOT / "script" / "project" / "init_env.py",
    PROJECT_ROOT / "script" / "project" / "generated_state.py",
    PROJECT_ROOT / "script" / "project" / "sync_generated_baseline.py",
    PROJECT_ROOT / "script" / "project" / "publish.py",
)

JSON_CONTRACT_FILES = (
    PROJECT_ROOT / ".flow" / "project.json",
    PROJECT_ROOT / ".flow" / "local.example.json",
    PROJECT_ROOT / "configs" / "data_quality.json",
    PROJECT_ROOT / "configs" / "source-policy.json",
    PROJECT_ROOT / "configs" / "generated-state.json",
    PROJECT_ROOT / "configs" / "wikiwiki-crawler.default.json",
    PACKAGE_SOURCE_DIR / "package.json",
)

GENERATED_STATE_REQUIRED_PATHS = (
    PACKAGE_DIR / "package.json",
    PACKAGE_DIR / "manifest.json",
    PACKAGE_DIR / "RELEASES.json",
)

GENERATED_STATE_JSON_CONTRACT_FILES = (
    PACKAGE_DIR / "package.json",
    PACKAGE_DIR / "manifest.json",
    PACKAGE_DIR / "RELEASES.json",
)


def _active_paths(paths: tuple[Path, ...], include_generated_state: bool) -> tuple[Path, ...]:
    if include_generated_state:
        return paths
    return tuple(
        path
        for path in paths
        if classify_path(PROJECT_ROOT, path.relative_to(PROJECT_ROOT).as_posix()) != "generated-state"
    )


def verify_project_shape(*, include_generated_state: bool = True) -> None:
    root_entry_names = {entry.name for entry in PROJECT_ROOT.iterdir()}
    if "README.md" not in root_entry_names:
        raise ProjectCommandError("根目录缺少精确大小写文件 README.md")
    if "readme.md" in root_entry_names:
        raise ProjectCommandError("根目录仍存在旧大小写文件 readme.md")
    if (PROJECT_ROOT / ".devops").exists():
        raise ProjectCommandError("Flow 1.1 项目不得继续跟踪 .devops 控制面")
    assert_paths_exist(_active_paths(REQUIRED_PATHS, include_generated_state))
    if include_generated_state:
        assert_paths_exist(GENERATED_STATE_REQUIRED_PATHS)


def verify_versions(*, include_generated_state: bool = True) -> None:
    version = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not SEMVER_RE.fullmatch(version):
        raise ProjectCommandError(f"项目 VERSION 不是合法 SemVer：{version!r}")
    package = json.loads((PACKAGE_SOURCE_DIR / "package.json").read_text(encoding="utf-8"))
    package_version = str(package.get("version", "")).strip()
    if not SEMVER_RE.fullmatch(package_version):
        raise ProjectCommandError(f"npm package.json 版本不是合法 SemVer：{package_version!r}")
    if include_generated_state:
        manifest = json.loads((PACKAGE_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest_version = str(manifest.get("packageVersion", "")).strip()
        if package_version != manifest_version:
            raise ProjectCommandError(
                f"npm 包版本不一致：package.json={package_version!r}, manifest.json={manifest_version!r}"
            )


def verify_json_contracts(*, include_generated_state: bool = True) -> None:
    paths = list(_active_paths(JSON_CONTRACT_FILES, include_generated_state))
    if include_generated_state:
        paths.extend(GENERATED_STATE_JSON_CONTRACT_FILES)
    for path in paths:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProjectCommandError(
                f"JSON 无效：{path.relative_to(PROJECT_ROOT)} 第 {exc.lineno} 行：{exc.msg}"
            ) from exc


def compile_python_sources() -> None:
    run(
        [sys.executable, "-m", "compileall", "-q", "configs", "pojo", "service", "util", "script"],
        cwd=PROJECT_ROOT,
        env=project_env(),
    )


def run_basic_checks(*, include_generated_state: bool = True) -> None:
    verify_project_shape(include_generated_state=include_generated_state)
    verify_versions(include_generated_state=include_generated_state)
    verify_json_contracts(include_generated_state=include_generated_state)
    verify_config_governance(PROJECT_ROOT)
    compile_python_sources()
