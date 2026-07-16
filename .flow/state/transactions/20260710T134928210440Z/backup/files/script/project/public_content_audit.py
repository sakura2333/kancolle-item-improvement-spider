from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class PublicContentAuditError(RuntimeError):
    pass


_MODULE_COMMAND_RE = re.compile(r"\bpython(?:3(?:\.\d+)?)?\s+-m\s+([A-Za-z_][A-Za-z0-9_.]*)")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_STRICT_PUBLIC_PATH_PREFIXES = (
    ".github/",
    "automation/",
    "docs/public/",
    "service/",
    "util/",
)
_PACKAGE_TEMPLATE_PREFIXES = (
    "packages/kancolle-data/schemas/",
    "packages/kancolle-data/scripts/",
)
_PACKAGE_TEMPLATE_FILES = {
    "packages/kancolle-data/CHANGELOG.md",
    "packages/kancolle-data/LICENSES.md",
    "packages/kancolle-data/README.md",
    "packages/kancolle-data/RELEASES.json",
    "packages/kancolle-data/index.d.ts",
    "packages/kancolle-data/index.js",
    "packages/kancolle-data/package.json",
}
_PUBLIC_ROOT_FILES = {
    "LICENSE",
    "README.md",
    "RELEASE-NOTES.md",
    "VERSION",
    "mise.toml",
    "pyproject.toml",
    "uv.lock",
    "PUBLIC-CONTENT-MANIFEST.json",
}
_RUNTIME_OUTPUT_PREFIXES = ("dist/", ".flow/local/")


def _module_exists(root: Path, module: str) -> bool:
    relative = Path(*module.split("."))
    return (root / relative.with_suffix(".py")).is_file() or (root / relative / "__init__.py").is_file()


def _source_path_reference(token: str) -> str | None:
    value = token.strip().strip("'\"(),:;")
    if not value or any(mark in value for mark in ("*", "{", "}", "$", "<", ">")):
        return None
    if " " in value or value.startswith(("http://", "https://")):
        return None
    if value.startswith(_RUNTIME_OUTPUT_PREFIXES):
        return None
    if value in _PUBLIC_ROOT_FILES or value.startswith(_STRICT_PUBLIC_PATH_PREFIXES):
        return value.rstrip("/")
    if value.startswith("configs/"):
        if ".local." in value or value.startswith(("configs/local/", "configs/schemas/")):
            return None
        if Path(value).suffix in {".json", ".py", ".md"}:
            return value.rstrip("/")
        return None
    if value in _PACKAGE_TEMPLATE_FILES or value.startswith(_PACKAGE_TEMPLATE_PREFIXES):
        return value.rstrip("/")
    return None


def inspect_public_text(root: Path, stable: dict[str, Any]) -> dict[str, Any]:
    """Validate that a Public Snapshot is self-contained and control-plane free.

    Runtime storage paths under ``.flow/local`` remain public implementation
    details because the acquisition runtime uses them.  Dev commands, internal
    documents, release state and missing source entry points are rejected before
    either Beta or Stable can consume the snapshot.
    """

    forbidden = [str(value) for value in stable.get("publicForbiddenText", [])]
    findings: list[dict[str, Any]] = []
    scanned = 0
    module_references = 0
    path_references = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        relative = path.relative_to(root).as_posix()
        lines = text.splitlines()
        for line_number, line in enumerate(lines, 1):
            for token in forbidden:
                if token in line:
                    findings.append(
                        {
                            "kind": "forbidden-text",
                            "path": relative,
                            "line": line_number,
                            "value": token,
                        }
                    )
            for module in _MODULE_COMMAND_RE.findall(line):
                module_references += 1
                if not _module_exists(root, module):
                    findings.append(
                        {
                            "kind": "missing-module-entrypoint",
                            "path": relative,
                            "line": line_number,
                            "value": module,
                        }
                    )
            if path.suffix.lower() != ".md":
                continue
            for inline in _INLINE_CODE_RE.findall(line):
                referenced = _source_path_reference(inline)
                if referenced is None:
                    continue
                path_references += 1
                target = root / referenced
                if not target.exists():
                    findings.append(
                        {
                            "kind": "missing-public-path",
                            "path": relative,
                            "line": line_number,
                            "value": referenced,
                        }
                    )

    if findings:
        details = "\n".join(
            f"{item['path']}:{item['line']}: {item['kind']}={item['value']}"
            for item in findings[:50]
        )
        raise PublicContentAuditError(
            "Public Snapshot 包含内部入口或失效引用：\n" + details
        )
    return {
        "schemaVersion": 2,
        "policy": "mechanical-public-boundary",
        "scannedTextFiles": scanned,
        "forbiddenTokens": forbidden,
        "moduleReferenceCount": module_references,
        "pathReferenceCount": path_references,
        "findingCount": 0,
    }
