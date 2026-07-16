from __future__ import annotations

"""Spider engineering-tool configuration.

This module belongs to the project tool layer.  Flow only calls the public
project targets exposed by ``script.flow_adapter`` and does not interpret the
quality, Git or public-release policy stored here.
"""

PROJECT = {
    "id": "kancolle-item-improvement-spider",
    "versionFile": "VERSION",
}

GIT = {
    "development": {
        "branch": "dev",
        "remote": "origin",
        "url": "ssh://git@192.168.1.129:13022/personal/kancolle-item-improvement-spider.git",
    },
    "stable": {
        "branch": "main",
        "remote": "main-origin",
        "url": "git@github.com:sakura2333/kancolle-item-improvement-spider.git",
    },
}

QUALITY = {
    "before": [
        ["{python}", "script/project/python_runner.py", "script/project/check.py", "before"],
        ["{python}", "script/project/python_runner.py", "script/project/test.py", "before"],
    ],
    "after": [
        ["{python}", "script/project/python_runner.py", "script/project/check.py", "after"],
        ["{python}", "script/project/python_runner.py", "script/project/test.py", "after"],
    ],
    "quick": [
        ["{python}", "script/project/python_runner.py", "script/project/check.py", "before"],
        ["{python}", "script/project/python_runner.py", "script/project/test.py", "before"],
    ],
    "full": [
        ["{python}", "script/project/python_runner.py", "script/project/check.py", "before"],
        ["{python}", "script/project/python_runner.py", "script/project/test.py", "all"],
        ["{python}", "script/project/python_runner.py", "script/project/verify.py"],
    ],
    # Internal release-only profile. It is intentionally not exposed as a
    # public `flow check` profile and is executed by Stable Preview.
    "release": [
        [
            "{python}",
            "script/project/python_runner.py",
            "script/project/test.py",
            "--pattern",
            "release_test*.py",
        ],
    ],
}

from script.project.main_content import load_main_content

STABLE = load_main_content()


def load() -> dict:
    return {
        "project": PROJECT,
        "git": GIT,
        "quality": QUALITY,
        "stable": STABLE,
    }
