from __future__ import annotations

import math
from pathlib import Path

from service.data_package.builder import PACKAGE_DIR

from .common import QualityGateError, _read_json
from .constants import DEFAULT_CONFIG_PATH
from .snapshot import inspect_package

def _load_config(path: Path) -> dict:
    config = _read_json(path)
    if not isinstance(config, dict):
        raise QualityGateError("quality gate config must be an object")
    return config

def validate_against_baseline(
    baseline: dict,
    current: dict,
    config: dict,
) -> list[str]:
    errors: list[str] = []
    metrics = current.get("metrics", {})
    baseline_metrics = baseline.get("metrics", {}) if isinstance(baseline, dict) else {}

    for metric, minimum in config.get("minimums", {}).items():
        value = metrics.get(metric)
        if not isinstance(value, (int, float)) or value < minimum:
            errors.append(f"{metric}={value!r} is below absolute minimum {minimum}")

    for metric, ratio in config.get("relativeMinimumRatios", {}).items():
        previous = baseline_metrics.get(metric)
        value = metrics.get(metric)
        if not isinstance(previous, (int, float)) or previous <= 0:
            continue
        if not isinstance(value, (int, float)):
            errors.append(f"{metric} is missing from current metrics")
            continue
        minimum = math.floor(previous * float(ratio))
        if value < minimum:
            errors.append(
                f"{metric} dropped from {previous} to {value}; minimum allowed at ratio {ratio} is {minimum}"
            )

    file_ratio = float(config.get("fileSizeMinimumRatio", 0))
    baseline_files = baseline.get("files", {}) if isinstance(baseline, dict) else {}
    current_files = current.get("files", {})
    for relative in config.get("fileSizePaths", []):
        previous = baseline_files.get(relative, {}).get("bytes")
        value = current_files.get(relative, {}).get("bytes")
        if not isinstance(previous, int) or previous <= 1:
            continue
        if not isinstance(value, int):
            errors.append(f"required file disappeared: {relative}")
            continue
        minimum = math.floor(previous * file_ratio)
        if value < minimum:
            errors.append(
                f"{relative} shrank from {previous} bytes to {value}; minimum allowed at ratio {file_ratio} is {minimum}"
            )
    return errors

def validate_package(
    baseline_path: Path,
    config_path: Path = DEFAULT_CONFIG_PATH,
    package_dir: Path = PACKAGE_DIR,
) -> tuple[dict, bool]:
    baseline = _read_json(baseline_path)
    current = inspect_package(package_dir=package_dir, require_fresh_sources=True)
    config = _load_config(config_path)
    errors = validate_against_baseline(baseline, current, config)
    if errors:
        raise QualityGateError("data quality gate failed:\n- " + "\n- ".join(errors))
    return current, current.get("contentDigest") != baseline.get("contentDigest")
