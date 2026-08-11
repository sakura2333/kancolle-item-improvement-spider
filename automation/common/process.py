from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence


class AutomationError(RuntimeError):
    """Raised when a public automation command cannot complete safely."""


def command_text(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(item)) for item in command)


def project_env(root: Path, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PYTHONPATH", "")
    root_text = str(root.resolve())
    env["PYTHONPATH"] = root_text if not current else os.pathsep.join((root_text, current))
    if extra:
        env.update({str(key): str(value) for key, value in extra.items()})
    return env


def run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    normalized = [str(item) for item in command]
    print(f"$ {command_text(normalized)}", flush=True)
    return subprocess.run(
        normalized,
        cwd=cwd,
        env=dict(env) if env is not None else project_env(cwd),
        check=True,
        text=True,
        capture_output=capture_output,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_json_output(output: str) -> Any:
    text = output.strip()
    if not text:
        raise AutomationError("command did not output JSON")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [index for index, char in enumerate(text) if char in "[{"]
    for index in reversed(starts):
        try:
            return json.loads(text[index:])
        except json.JSONDecodeError:
            continue
    raise AutomationError("could not parse JSON from command output")
