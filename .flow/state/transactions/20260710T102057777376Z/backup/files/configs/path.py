import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Stable project-owned data. Keep only README / fixtures / seed here.
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

# Flow-local runtime state. Never commit.
FLOW_DIR = os.path.join(PROJECT_ROOT, ".flow")
FLOW_LOCAL_DIR = os.path.join(FLOW_DIR, "local")
SOURCE_CACHE_DIR = os.path.join(FLOW_LOCAL_DIR, "source-cache")

# Re-runnable outputs. Never commit.
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
DIST_DATA_PIPELINE_DIR = os.path.join(DIST_DIR, "data-pipeline")
DIST_PACKAGE_DIR = os.path.join(DIST_DIR, "packages")

LOG_DIR = os.path.join(PROJECT_ROOT, "log")
TEMP_DIR = os.path.join(PROJECT_ROOT, "script")

for d in [
    DATA_DIR,
    FLOW_LOCAL_DIR,
    SOURCE_CACHE_DIR,
    DIST_DIR,
    DIST_DATA_PIPELINE_DIR,
    DIST_PACKAGE_DIR,
    LOG_DIR,
    TEMP_DIR,
]:
    os.makedirs(d, exist_ok=True)


def _child(root: str, subfolder: str = "") -> str:
    path = os.path.join(root, subfolder) if subfolder else root
    os.makedirs(path, exist_ok=True)
    return path


def get_flow_local_dir(subfolder: str = "") -> str:
    return _child(FLOW_LOCAL_DIR, subfolder)


def get_source_cache_dir(subfolder: str = "") -> str:
    return _child(SOURCE_CACHE_DIR, subfolder)


def get_dist_dir(subfolder: str = "") -> str:
    return _child(DIST_DIR, subfolder)


def get_raw_data_dir(subfolder: str = "") -> str:
    """Compatibility alias for local source cache."""
    return get_source_cache_dir(subfolder)


def get_data_dir(subfolder: str = "") -> str:
    return _child(DATA_DIR, subfolder)


def get_db_dir(subfolder: str = "") -> str:
    if subfolder in {"improvement", "start2_data", "assets", "sources", "work"}:
        return get_dist_dir(os.path.join("data-pipeline", subfolder))
    return get_data_dir(subfolder)


def get_log_dir(file_name: str = "") -> str:
    return os.path.join(LOG_DIR, file_name) if file_name else LOG_DIR


def get_temp_dir(file_name: str = "") -> str:
    return os.path.join(TEMP_DIR, file_name) if file_name else TEMP_DIR
