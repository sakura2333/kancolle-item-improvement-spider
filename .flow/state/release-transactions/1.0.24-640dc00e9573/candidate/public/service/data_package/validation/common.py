from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

class QualityGateError(ValueError):
    pass

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise QualityGateError(f"invalid JSON file {path}: {exc}") from exc

def _read_nedb(path: Path) -> list[dict]:
    records: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        raise QualityGateError(f"cannot read NeDB file {path}: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except Exception as exc:
            raise QualityGateError(f"invalid NeDB JSON at {path}:{line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise QualityGateError(f"NeDB record at {path}:{line_number} is not an object")
        records.append(record)
    return records

def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0

def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())

