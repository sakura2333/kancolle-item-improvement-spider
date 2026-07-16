from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Any


class PublicContentAuditError(RuntimeError):
    pass


_MODULE_COMMAND_RE = re.compile(r"\bpython(?:3(?:\.\d+)?)?\s+-m\s+([A-Za-z_][A-Za-z0-9_.]*)")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_ABSOLUTE_LOCAL_PATH_RE = re.compile(r"(?:/Users/|/home/[^/\s]+/|[A-Za-z]:\\Users\\)")
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
    ".gitignore",
    "LICENSE",
    "README.md",
    "RELEASE-NOTES.md",
    "VERSION",
    "mise.toml",
    "pyproject.toml",
    "uv.lock",
    "PUBLIC-CONTENT-MANIFEST.json",
}
_RUNTIME_OUTPUT_PREFIXES = ("dist/", ".spider/local/")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _matches(path: str, pattern: str) -> bool:
    import fnmatch

    value = path.replace("\\", "/").strip("/")
    expected = pattern.replace("\\", "/").strip("/")
    base = expected[:-3] if expected.endswith("/**") else expected
    return value == base or value.startswith(base + "/") or fnmatch.fnmatch(value, expected)


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


def _exception_contract(stable: dict[str, Any]) -> tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]:
    payload = stable.get("publicExceptions")
    if payload is None and not stable.get("publicReviewText"):
        return {}, []
    entries = payload.get("exceptions") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise PublicContentAuditError("Public Snapshot 缺少已验证的例外清单")
    match_map: dict[tuple[str, str], dict[str, Any]] = {}
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        identifier = str(entry["id"])
        normalized.append(entry)
        for match in entry.get("matches", []):
            key = (str(match["path"]), str(match["literal"]))
            if key in match_map:
                raise PublicContentAuditError(f"公开例外重复登记：{key}")
            match_map[key] = {
                "id": identifier,
                "expectedOccurrences": int(match["expectedOccurrences"]),
                "forbiddenContent": [str(value) for value in entry.get("forbiddenContent", [])],
            }
    return match_map, normalized


def inspect_public_checkout(root: Path, stable: dict[str, Any]) -> dict[str, Any]:
    ignore = root / ".gitignore"
    if not ignore.is_file():
        raise PublicContentAuditError("Public Snapshot 缺少 .gitignore")
    with tempfile.TemporaryDirectory(prefix="spider-public-checkout-") as temp_name:
        checkout = Path(temp_name) / "checkout"
        import shutil

        shutil.copytree(root, checkout)
        subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
        subprocess.run(["git", "config", "user.name", "public-check"], cwd=checkout, check=True)
        subprocess.run(["git", "config", "user.email", "public-check@example.invalid"], cwd=checkout, check=True)
        subprocess.run(["git", "add", "-A"], cwd=checkout, check=True)
        subprocess.run(["git", "commit", "-qm", "public snapshot"], cwd=checkout, check=True)
        generated = [
            checkout / ".venv/bin/python",
            checkout / ".spider/local/source-cache/page.html",
            checkout / "dist/data-pipeline/result.json",
            checkout / "configs/wikiwiki-crawler.local.json",
            checkout / "service/__pycache__/module.pyc",
            checkout / "packages/kancolle-data/package.tgz",
            checkout / ".DS_Store",
        ]
        for path in generated:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("generated\n", encoding="utf-8")
        completed = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=checkout,
            text=True,
            capture_output=True,
            check=True,
        )
        if completed.stdout.strip():
            raise PublicContentAuditError(
                "Public Snapshot 运行后工作树不干净：\n" + completed.stdout.strip()
            )
    return {
        "schemaVersion": 1,
        "policy": "fresh-public-checkout-clean",
        "generatedProbeCount": len(generated),
        "dirtyPathCount": 0,
    }


def inspect_public_text(root: Path, stable: dict[str, Any]) -> dict[str, Any]:
    """Validate that a Public Snapshot is self-contained and control-plane free.

    Internal semantics are denied by default.  Public functionality that must
    retain a sensitive-looking term is accepted only through the exact,
    versioned exception manifest loaded from ``release/public-exceptions.json``.
    """

    forbidden = [str(value) for value in stable.get("publicForbiddenText", [])]
    review_tokens = [str(value) for value in stable.get("publicReviewText", [])]
    match_map, exception_entries = _exception_contract(stable)
    actual_matches: dict[tuple[str, str], int] = {key: 0 for key in match_map}
    findings: list[dict[str, Any]] = []
    scanned = 0
    module_references = 0
    path_references = 0
    absolute_path_count = 0
    internal_reference_count = 0
    text_by_path: dict[str, str] = {}

    paths = [path for path in sorted(root.rglob("*")) if path.is_file() and not path.is_symlink()]
    internal_paths = [
        path.relative_to(root).as_posix()
        for path in paths
        if any(_matches(path.relative_to(root).as_posix(), pattern) for pattern in stable.get("internalOnly", []))
    ]
    if internal_paths:
        findings.extend({"kind": "internal-path", "path": value, "line": 0, "value": value} for value in internal_paths)

    for path in paths:
        data = path.read_bytes()
        if b"\0" in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        relative = path.relative_to(root).as_posix()
        text_by_path[relative] = text
        lines = text.splitlines()
        for line_number, line in enumerate(lines, 1):
            for token in forbidden:
                if token in line:
                    internal_reference_count += line.count(token)
                    findings.append({"kind": "forbidden-text", "path": relative, "line": line_number, "value": token})
            absolute_hits = _ABSOLUTE_LOCAL_PATH_RE.findall(line)
            if absolute_hits:
                absolute_path_count += len(absolute_hits)
                findings.append({"kind": "absolute-local-path", "path": relative, "line": line_number, "value": absolute_hits[0]})
            for token in review_tokens:
                count = line.count(token)
                if not count:
                    continue
                key = (relative, token)
                if key not in match_map:
                    findings.append({"kind": "unregistered-public-exception", "path": relative, "line": line_number, "value": token})
                else:
                    actual_matches[key] += count
            for module in _MODULE_COMMAND_RE.findall(line):
                module_references += 1
                if not _module_exists(root, module):
                    findings.append({"kind": "missing-module-entrypoint", "path": relative, "line": line_number, "value": module})
            if path.suffix.lower() != ".md":
                continue
            for inline in _INLINE_CODE_RE.findall(line):
                referenced = _source_path_reference(inline)
                if referenced is None:
                    continue
                path_references += 1
                if not (root / referenced).exists():
                    findings.append({"kind": "missing-public-path", "path": relative, "line": line_number, "value": referenced})

    exception_results: list[dict[str, Any]] = []
    for entry in exception_entries:
        identifier = str(entry["id"])
        entry_paths: set[str] = set()
        for match in entry.get("matches", []):
            key = (str(match["path"]), str(match["literal"]))
            expected = int(match["expectedOccurrences"])
            actual = actual_matches.get(key, 0)
            entry_paths.add(key[0])
            if actual != expected:
                findings.append({"kind": "public-exception-count-mismatch", "path": key[0], "line": 0, "value": f"{key[1]} expected={expected} actual={actual}"})
        reviewed_files: list[dict[str, str]] = []
        for value in entry.get("reviewFiles", []):
            relative = str(value)
            target = root / relative
            entry_paths.add(relative)
            if not target.is_file():
                findings.append({"kind": "public-exception-file-missing", "path": relative, "line": 0, "value": identifier})
            else:
                reviewed_files.append({"path": relative, "sha256": _sha256(target)})
        for relative in entry_paths:
            text = text_by_path.get(relative, "")
            for token in entry.get("forbiddenContent", []):
                if str(token) in text:
                    findings.append({"kind": "public-exception-forbidden-neighbor", "path": relative, "line": 0, "value": str(token)})
        exception_results.append(
            {
                "id": identifier,
                "category": entry["category"],
                "owner": entry["owner"],
                "review": entry["review"],
                "expires": entry.get("expires"),
                "reviewFiles": reviewed_files,
            }
        )

    if findings:
        details = "\n".join(f"{item['path']}:{item['line']}: {item['kind']}={item['value']}" for item in findings[:80])
        raise PublicContentAuditError("Public Snapshot 隔离或例外验证失败：\n" + details)
    checkout = (
        inspect_public_checkout(root, stable)
        if stable.get("publicGitignore") is not None
        else {"schemaVersion": 1, "policy": "not-configured", "generatedProbeCount": 0, "dirtyPathCount": 0}
    )
    return {
        "schemaVersion": 3,
        "policy": "deny-by-default-public-isolation",
        "scannedTextFiles": scanned,
        "forbiddenTokens": forbidden,
        "reviewTokens": review_tokens,
        "moduleReferenceCount": module_references,
        "pathReferenceCount": path_references,
        "findingCount": 0,
        "publicIsolation": {
            "internalPathCount": 0,
            "internalReferenceCount": internal_reference_count,
            "absolutePathCount": absolute_path_count,
            "exceptionCount": len(exception_results),
            "exceptionManifestSha256": stable.get("publicExceptionsSha256"),
            "exceptions": [item["id"] for item in exception_results],
        },
        "exceptionDetails": exception_results,
        "publicCheckout": checkout,
    }
