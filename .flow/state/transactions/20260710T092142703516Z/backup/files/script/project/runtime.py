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

STABLE = {
    "include": [
        ".github/workflows/data-pipeline.yml", "CHANGELOG.md", "DATA_PACKAGE_NOTES.md",
        "DATA_SCHEMA.md", "LICENSE", "README.md", "RELEASE-NOTES.md", "ROUTE_AUDIT_NOTES.md",
        "VERSION", "requirements.txt", "configs/**", "pojo/**", "service/**", "util/**",
        "dist/data-pipeline/improvement/**", "dist/data-pipeline/start2_data/**",
        "dist/data-pipeline/assets/**", "dist/data-pipeline/sources/**",
        "dist/packages/kancolle-data/**", "packages/kancolle-data/**", "docs/public/**",
    ],
    "required": [
        "README.md", "VERSION", "DATA_SCHEMA.md", "DATA_PACKAGE_NOTES.md", "RELEASE-NOTES.md",
        "docs/public/README.md", ".github/workflows/data-pipeline.yml",
        "STABLE-CONTENT-MANIFEST.json",
    ],
    "internalOnly": [
        ".flow/**", "script/**", "tests/**", "docs/internal/**", "AGENTS.md", "GPT-START.md",
        "SPIDER-HARD-RULES.md", "SPIDER-AUTHORITY-MAP.md", "data/raw_data/**", ".flow/local/**", "log/**",
    ],
    "summary": {"builder": "script.project.release_summary:build"},
    "previewRoot": ".flow/state/stable",
    "mainReleaseGateRoot": ".flow/state/main-release",
    "candidateBranchPrefix": "public-candidate/",
    "contentManifest": {
        "path": "STABLE-CONTENT-MANIFEST.json",
        "migrationId": "spider-flow-public-1.0.4",
        "mode": "one-time-full-then-managed",
        "allowedLegacyTrees": ["4065dfa2cc3732c2c2ca70d60ec889dc24d738fe"],
    },
    "generated": ["RELEASE-NOTES.md", "STABLE-CONTENT-MANIFEST.json"],
    "releaseCheckProfile": "release",
    "npmRelease": {
        "package": "@sakura2333/kancolle-data",
        "currentTag": "latest",
        "compatibilityConsumer": "poi-plugin-item-improvement2",
        "compatibilityTag": "improvement2",
        "publishMode": "manual-npm-auth-then-flow-reconcile",
    },
}


def load() -> dict:
    return {
        "project": PROJECT,
        "git": GIT,
        "quality": QUALITY,
        "stable": STABLE,
    }
