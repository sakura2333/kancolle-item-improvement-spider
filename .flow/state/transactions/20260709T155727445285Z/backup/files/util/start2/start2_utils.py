import json
import os
import time
import requests


def _strict_mode():
    return os.getenv("DATA_PACKAGE_STRICT", "0").strip().lower() in {"1", "true", "yes", "on"}

from util.logger import simple_logger
from util.start2.config import start2_dir

WORK_DIR = start2_dir
os.makedirs(WORK_DIR, exist_ok=True)

INDEX_URL = "https://api.kcwiki.moe/start2/archives"
DATA_URL = "https://api.kcwiki.moe/start2"


# ---------------------------
# HTTP 工具
# ---------------------------
def get_json(url):
    last_error = None
    for _ in range(3):
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_error = e
            time.sleep(2)
    raise RuntimeError(f"failed to fetch: {url}") from last_error


# ---------------------------
# remote index（不缓存）
# ---------------------------
def fetch_remote_index():
    return get_json(INDEX_URL)


# ---------------------------
# local version
# ---------------------------
VERSION_FILE = os.path.join(WORK_DIR, "current_version.txt")


def get_local_version():
    if not os.path.exists(VERSION_FILE):
        return None
    with open(VERSION_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()


def set_local_version(v: str):
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(v)


# ---------------------------
# 拉取 full start2
# ---------------------------
def fetch_start2():
    return get_json(DATA_URL)


# ---------------------------
# split
# ---------------------------
def split_start2(data: dict):
    for key, value in data.items():
        file_path = os.path.join(WORK_DIR, f"{key}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)


def load_start2_readers():
    from util.start2.start2_item_utils import start2ItemUtils
    from util.start2.start2_ship_utils import ship_utils
    from util.start2.start2_use_item_utils import start2ConsumeUseUtils

    start2ItemUtils.reload()
    ship_utils.reload()
    start2ConsumeUseUtils.reload()

    start2ItemUtils.load()
    ship_utils.load()
    start2ConsumeUseUtils.load()


# ---------------------------
# 核心更新逻辑
# ---------------------------
def update_start2_if_needed():
    updated_version = None

    try:
        remote_index = fetch_remote_index()
    except Exception as e:
        if _strict_mode():
            raise RuntimeError(f"[start2] strict mode could not validate remote index: {e}") from e
        simple_logger.warn(f"[start2] failed to fetch remote index, skip update: {e}")
    else:
        if not remote_index:
            raise RuntimeError("remote index empty")

        latest_version = remote_index[-1]
        local_version = get_local_version()

        simple_logger.info(f"[start2] local={local_version}, remote={latest_version}")

        if local_version == latest_version:
            simple_logger.info("[start2] no update needed")
        else:
            simple_logger.info("[start2] updating...")

            try:
                data = fetch_start2()
            except Exception as e:
                if _strict_mode():
                    raise RuntimeError(f"[start2] strict mode could not download current data: {e}") from e
                simple_logger.warn(f"[start2] failed to fetch start2, skip update: {e}")
            else:
                split_start2(data)
                updated_version = latest_version

    load_start2_readers()

    if updated_version is not None:
        set_local_version(updated_version)
        simple_logger.info(f"[start2] updated to {updated_version}")


# ---------------------------
# entry
# ---------------------------
if __name__ == "__main__":
    update_start2_if_needed()
