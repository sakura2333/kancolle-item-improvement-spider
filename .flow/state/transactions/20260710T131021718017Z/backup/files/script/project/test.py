#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from _common import PROJECT_ROOT, main_guard, project_env, run

BEFORE_TEST_MODULES = (
    "tests.test_config_guard",
    "tests.test_directory_governance",
    "tests.test_external_tooling_boundary",
    "tests.test_main_boundary",
    "tests.test_main_beta_release",
    "tests.test_public_automation_bundle",
    "tests.test_operator_stop",
    "tools/" "wikiwiki-crawler/tests/test_crawler.py",
    "tests.test_generated_state",
    "tests.test_project_commands",
    "tests.test_flow_command",
    "tests.test_python_environment",
    "tests.test_text_normalization",
    "tests.test_quality_profile_boundaries",
    "tests.test_script_convergence",
    "tests.test_command_support",
    "tests.test_source_phase",
    "tests.test_smoke_flow_command",
    "tests.test_run_flow_command",
    "tests.test_kcwiki_nonblocking",
    "tests.test_improvement_assistant_reverse",
    "tests.test_wikiwiki_flow_command",
    "tests.test_wikiwiki_crawler",
)

AFTER_TEST_MODULES = (
    "tests.test_data_package",
    "tests.test_equipment_acquisition",
    "tests.test_route_variants",
    "tests.test_ship_name_resolver",
    "tests.test_source_validation",
    "tests.test_release_summary",
    "tests.test_data_quality_gate",
    "tests.test_reliability_logging",
)


def _run_modules(modules: tuple[str, ...]) -> None:
    run(
        [sys.executable, "-m", "unittest", *modules, "-v"],
        cwd=PROJECT_ROOT,
        env=project_env(),
    )


def _run_discover(pattern: str) -> None:
    run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            pattern,
            "-v",
        ],
        cwd=PROJECT_ROOT,
        env=project_env(),
    )


def execute(phase: str = "before", *, pattern: str = "test*.py") -> None:
    if phase == "before":
        _run_modules(BEFORE_TEST_MODULES)
        return
    if phase == "after":
        _run_modules(AFTER_TEST_MODULES)
        return
    if phase == "all":
        _run_discover(pattern)
        return
    raise ValueError(f"不支持的测试阶段：{phase}")


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 Spider 单元测试；默认 before，不依赖生成数据")
    parser.add_argument("phase", nargs="?", choices=("before", "after", "all"), default="before")
    parser.add_argument("--pattern", default="test*.py", help="仅 all 阶段使用的 unittest 文件匹配模式")
    args = parser.parse_args()
    return main_guard(lambda: execute(args.phase, pattern=args.pattern))


if __name__ == "__main__":
    raise SystemExit(main())
