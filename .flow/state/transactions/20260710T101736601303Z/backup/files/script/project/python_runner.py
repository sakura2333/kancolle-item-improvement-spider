#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _common_repository_root(root: Path) -> Path | None:
    completed = subprocess.run(
        ['git', '-C', str(root), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode or not completed.stdout.strip():
        return None
    common_dir = Path(completed.stdout.strip()).resolve()
    return common_dir.parent if common_dir.name == '.git' else None


def _python_candidates(root: Path) -> tuple[Path, ...]:
    roots: list[Path] = [root]
    common_root = _common_repository_root(root)
    if common_root is not None and common_root not in roots:
        roots.append(common_root)
    candidates: list[Path] = []
    for candidate_root in roots:
        candidates.extend((
            candidate_root / '.venv' / 'bin' / 'python3',
            candidate_root / '.venv' / 'bin' / 'python',
        ))
    return tuple(candidates)


def main() -> int:
    if len(sys.argv) < 2:
        print('用法：python3 script/project/python_runner.py <script> [args...]', file=sys.stderr)
        return 2
    root = _project_root()
    selected = next((path for path in _python_candidates(root) if path.is_file() and os.access(path, os.X_OK)), None)
    interpreter = str(selected) if selected is not None else sys.executable
    target = Path(sys.argv[1])
    if not target.is_absolute():
        target = root / target
    os.execv(interpreter, [interpreter, str(target), *sys.argv[2:]])
    return 127


if __name__ == '__main__':
    raise SystemExit(main())
