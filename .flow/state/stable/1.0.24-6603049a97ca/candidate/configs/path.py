from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

FLOW_DIR = os.path.join(PROJECT_ROOT, ".flow")
FLOW_LOCAL_DIR = os.path.join(FLOW_DIR, "local")
SOURCE_CACHE_DIR = os.path.join(FLOW_LOCAL_DIR, "source-cache")
LOCAL_LOG_DIR = os.path.join(FLOW_LOCAL_DIR, "logs", "business")

DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
DIST_DATA_PIPELINE_DIR = os.path.join(DIST_DIR, "data-pipeline")
DIST_PACKAGE_DIR = os.path.join(DIST_DIR, "packages")


def _child(root: str, subfolder: str = "", *, create: bool = True) -> str:
    path = os.path.join(root, subfolder) if subfolder else root
    if create:
        Path(path).mkdir(parents=True, exist_ok=True)
    return path


def get_flow_local_dir(subfolder: str = "") -> str:
    return _child(FLOW_LOCAL_DIR, subfolder)


def get_source_cache_dir(subfolder: str = "") -> str:
    return _child(SOURCE_CACHE_DIR, subfolder)


def get_dist_dir(subfolder: str = "") -> str:
    return _child(DIST_DIR, subfolder)


def get_data_pipeline_dir(subfolder: str = "") -> str:
    return _child(DIST_DATA_PIPELINE_DIR, subfolder)


def get_package_dist_dir(subfolder: str = "") -> str:
    return _child(DIST_PACKAGE_DIR, subfolder)


def get_log_dir(file_name: str = "") -> str:
    root = _child(LOCAL_LOG_DIR)
    return os.path.join(root, file_name) if file_name else root
