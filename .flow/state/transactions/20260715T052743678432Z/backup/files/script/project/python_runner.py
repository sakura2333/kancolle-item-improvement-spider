#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    if len(sys.argv) < 2:
        print('用法：python3 script/project/python_runner.py <script> [args...]', file=sys.stderr)
        return 2
    mise = shutil.which('mise')
    if not mise:
        print('未找到 mise；请先安装并启用 mise', file=sys.stderr)
        return 20
    root = _project_root()
    target = Path(sys.argv[1])
    if not target.is_absolute():
        target = root / target
    os.environ['MISE_TRUSTED_CONFIG_PATHS'] = str(root)
    argv = [
        mise,
        'exec',
        '--',
        'uv',
        'run',
        '--locked',
        '--project',
        str(root),
        'python',
        str(target),
        *sys.argv[2:],
    ]
    os.execv(mise, argv)
    return 127


if __name__ == '__main__':
    raise SystemExit(main())
