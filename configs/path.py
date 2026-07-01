import os

# 项目根目录：configs 的上一级
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# 基础目录
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
RAW_DATA_DIR = os.path.join(DATA_DIR, "raw_data")  # 新增：原始数据目录
LOG_DIR = os.path.join(PROJECT_ROOT, "log")
TEMP_DIR = os.path.join(PROJECT_ROOT, "script")

# 确保目录存在
# 将 RAW_DATA_DIR 加入循环自动创建
for d in [DATA_DIR, RAW_DATA_DIR, LOG_DIR, TEMP_DIR]:
    os.makedirs(d, exist_ok=True)

# --- 增加对应的获取函数 ---

def get_raw_data_dir(subfolder: str = "") -> str:
    """获取原始数据存放目录"""
    path = os.path.join(RAW_DATA_DIR, subfolder) if subfolder else RAW_DATA_DIR
    os.makedirs(path, exist_ok=True)
    return path

# --- 原有函数保持不变 ---

def get_data_dir(subfolder: str = "") -> str:
    path = os.path.join(DATA_DIR, subfolder) if subfolder else DATA_DIR
    os.makedirs(path, exist_ok=True)
    return path

def get_db_dir(subfolder: str = "") -> str:
    path = os.path.join(DATA_DIR, subfolder) if subfolder else DATA_DIR
    os.makedirs(path, exist_ok=True)
    return path

def get_log_dir(file_name: str = "") -> str:
    return os.path.join(LOG_DIR, file_name) if file_name else LOG_DIR

def get_temp_dir(file_name: str = "") -> str:
    return os.path.join(TEMP_DIR, file_name) if file_name else TEMP_DIR
