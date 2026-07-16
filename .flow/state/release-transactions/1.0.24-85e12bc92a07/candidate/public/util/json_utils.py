import json
from pathlib import Path
from typing import Any, Union, List

from util.logger import simple_logger


def write_file(
    file_path: Union[str, Path],
    content: str,
    mode: str = "w",
    log: bool = True
) -> None:
    """
    基础写文件函数
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode, encoding="utf-8") as f:
        f.write(content)
    if log:
        simple_logger.debug(f"[fileutils] 写入文件: {path} (mode={mode})")

def write_json_lines(
    file_path: Union[str, Path],
    data_list: List[Any],
    mode: str = "w",
    log: bool = True
) -> int:
    """
    将列表的每个元素写入文件，每行一个 JSON
    - mode: "w" 覆盖, "a" 追加
    返回写入的记录数
    """
    content = "\n".join(json.dumps(item, ensure_ascii=False) for item in data_list)
    write_file(file_path, content + "\n", mode=mode, log=log)
    return len(data_list)

def write_json(
    file_path: Union[str, Path],
    data: Union[dict, list],
    mode: str = "w",
    log: bool = True
) -> None:
    """
    写单个 JSON 文件
    - data: 可以是 dict 或 list
    - mode: "w" 覆盖, "a" 追加（追加只支持 list，每次追加新元素）
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if mode == "a" and isinstance(data, list) and path.exists():
        # 如果是追加 list，先读取原来的内容
        with open(path, "r", encoding="utf-8") as f:
            try:
                old_data = json.load(f)
                if not isinstance(old_data, list):
                    old_data = []
            except json.JSONDecodeError:
                old_data = []
        data = old_data + data

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if log:
        print(f"[fileutils] 写入 JSON 文件: {path} (mode={mode})")

def read_json_lines(file_path: Union[str, Path]) -> List[Any]:
    """
    按行读取 JSON 文件，每行一个 JSON 对象
    返回对象列表
    """
    path = Path(file_path)
    if not path.exists():
        return []

    result = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return result


def read_json(file_path: Union[str, Path]) -> Any:
    """
    读取整个 JSON 文件（dict 或 list）
    """
    path = Path(file_path)
    if not path.exists():
        return None

    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return None