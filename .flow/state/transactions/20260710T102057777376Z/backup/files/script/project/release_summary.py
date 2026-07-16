#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "RELEASE-NOTES.md"
REPORT = ROOT / "dist" / "release-summary" / "aggregate.json"

INTERNAL_PATTERN = re.compile(
    r"(?:\bdevops\b|\bgpt\b|\bflow\b|\breceipt\b|\bevidence\b|"
    r"\.devops|\.flow|origin/dev|main-origin|内部|内网|治理|门禁|迁移|流水线实现|"
    r"actions?\s+(?:run|log|artifact|cache|secret|variable))",
    re.IGNORECASE,
)
HEADING_PATTERN = re.compile(r"^#{2,4}\s+(.+?)\s*$")
VERSION_HEADING = re.compile(r"^##\s+\[([^\]]+)\](?:\s+-\s+([^\s]+))?\s*$")
BULLET_PATTERN = re.compile(r"^\s*[-*]\s+(.+?)\s*$")
PUBLIC_SECTIONS = {
    "added": "新增",
    "changed": "变化",
    "fixed": "修复",
    "removed": "移除",
    "compatibility": "兼容性",
    "validation": "验证",
}


@dataclass(frozen=True)
class LogEntry:
    source: str
    version: str
    section: str
    text: str
    public: bool


@dataclass(frozen=True)
class Note:
    section: str
    text: str
    source: str


def _run(*args: str) -> str:
    completed = subprocess.run(
        list(args), cwd=ROOT, text=True, capture_output=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_version() -> str:
    return (ROOT / "VERSION").read_text("utf-8").strip()


def _release_date(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text("utf-8")
    match = re.search(
        rf"(?m)^##\s+\[{re.escape(version)}\]\s+-\s+([^\s]+)\s*$", text
    )
    if match:
        return match.group(1)
    value = _run("git", "show", "-s", "--format=%cs", "HEAD")
    return value or "unknown"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip("。.") + "。"


def _is_public(text: str) -> bool:
    return bool(text.strip()) and INTERNAL_PATTERN.search(text) is None


def _extract_changelog_entries(path: Path, selectors: set[str]) -> list[LogEntry]:
    lines = path.read_text("utf-8").splitlines()
    active_version = ""
    active_section = ""
    entries: list[LogEntry] = []
    for line in lines:
        version_match = VERSION_HEADING.match(line)
        if version_match:
            active_version = version_match.group(1).strip()
            active_section = ""
            continue
        heading = HEADING_PATTERN.match(line)
        if heading:
            active_section = heading.group(1).strip()
            continue
        bullet = BULLET_PATTERN.match(line)
        if not bullet or active_version not in selectors:
            continue
        text = _normalize(bullet.group(1))
        section_key = active_section.casefold()
        entries.append(
            LogEntry(
                source=path.relative_to(ROOT).as_posix(),
                version=active_version,
                section=active_section,
                text=text,
                public=section_key in PUBLIC_SECTIONS and _is_public(text),
            )
        )
    return entries


def _public_notes(entries: Iterable[LogEntry]) -> list[Note]:
    notes: list[Note] = []
    for entry in entries:
        if not entry.public:
            continue
        section = PUBLIC_SECTIONS.get(entry.section.casefold())
        if section:
            notes.append(Note(section, entry.text, entry.source))
    return notes


def _package_version() -> str:
    path = ROOT / "packages" / "kancolle-data" / "package.json"
    if not path.is_file():
        return ""
    raw = json.loads(path.read_text("utf-8"))
    return str(raw.get("version", "")).strip()


def _latest_release_record() -> dict[str, object]:
    path = ROOT / "packages" / "kancolle-data" / "RELEASES.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text("utf-8"))
    if not isinstance(raw, list) or not raw:
        return {}
    package_version = _package_version()
    matching = [item for item in raw if isinstance(item, dict) and item.get("version") == package_version]
    item = matching[-1] if matching else raw[-1]
    return item if isinstance(item, dict) else {}


def _git_commits() -> list[str]:
    baseline = ""
    for ref in ("main-origin/main", "origin/main", "main"):
        if _run("git", "rev-parse", "--verify", ref):
            baseline = ref
            break
    range_value = f"{baseline}..HEAD" if baseline else "HEAD"
    raw = _run("git", "log", "--format=%s", range_value)
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _dedupe(notes: Iterable[Note]) -> list[Note]:
    result: list[Note] = []
    seen: set[str] = set()
    for note in notes:
        identity = hashlib.sha256(note.text.casefold().encode("utf-8")).hexdigest()
        if identity in seen:
            continue
        seen.add(identity)
        result.append(note)
    return result


def _metrics_lines(release_record: dict[str, object]) -> list[str]:
    raw = release_record.get("metrics")
    if not isinstance(raw, dict):
        return []
    mapping = (
        ("improvement.detailRecordCount", "改修路线明细"),
        ("equipmentDropFrom.recordCount", "装备获得记录"),
        ("equipmentSpecialBonuses.recordCount", "特殊装备加成记录"),
        ("useitemIcons.count", "消耗品图片"),
    )
    result = []
    for key, label in mapping:
        value = raw.get(key)
        if isinstance(value, int):
            result.append(f"- {label}：{value}")
    return result


def _source_records(paths: Iterable[Path]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for path in paths:
        if not path.is_file():
            continue
        result.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": _sha256(path),
                "sizeBytes": path.stat().st_size,
            }
        )
    result.append({"path": "git log", "head": _run("git", "rev-parse", "HEAD")})
    return result



def _json_source(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"path": path.relative_to(ROOT).as_posix(), "exists": False}
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "path": path.relative_to(ROOT).as_posix(),
            "exists": True,
            "sha256": _sha256(path),
            "parseError": str(exc),
        }
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "exists": True,
        "sha256": _sha256(path),
        "value": value,
    }


def _structured_evidence() -> list[dict[str, object]]:
    paths = (
        ROOT / ".flow" / "state" / "checks" / "before.json",
        ROOT / ".flow" / "state" / "checks" / "after.json",
        ROOT / "dist" / "packages" / "kancolle-data" / "audit" / "build-report.json",
        ROOT / "dist" / "data-pipeline" / "sources" / "comparison" / "summary.json",
    )
    return [_json_source(path) for path in paths]

def build() -> tuple[str, dict[str, object]]:
    version = _project_version()
    package_version = _package_version()
    project_changelog = ROOT / "CHANGELOG.md"
    package_changelog = ROOT / "packages" / "kancolle-data" / "CHANGELOG.md"
    releases_path = ROOT / "packages" / "kancolle-data" / "RELEASES.json"

    entries = _extract_changelog_entries(project_changelog, {version})
    if package_changelog.is_file():
        selectors = {"Unreleased"}
        if package_version:
            selectors.add(package_version)
        entries.extend(_extract_changelog_entries(package_changelog, selectors))

    notes = _dedupe(_public_notes(entries))
    release_record = _latest_release_record()
    commits = _git_commits()
    commit_records = [
        {"subject": subject, "public": _is_public(subject)} for subject in commits
    ]

    grouped: dict[str, list[str]] = {}
    for note in notes:
        grouped.setdefault(note.section, []).append(note.text)

    lines = [
        "# Release Notes",
        "",
        f"## {version} ({_release_date(version)})",
        "",
        "本页由发布候选生成器汇总项目 Changelog、数据包 Changelog、机器发布记录和本次 Git 变更后生成。只保留面向使用者和数据消费方的摘要。",
        "",
    ]
    for section in ("新增", "变化", "修复", "移除", "兼容性", "验证"):
        section_entries = grouped.get(section, [])
        if not section_entries:
            continue
        lines.extend((f"### {section}", ""))
        lines.extend(f"- {item}" for item in section_entries)
        lines.append("")

    metric_lines = _metrics_lines(release_record)
    if metric_lines:
        lines.extend(("### 数据快照", ""))
        if package_version:
            lines.append(f"数据包版本：`@sakura2333/kancolle-data@{package_version}`")
            lines.append("")
        lines.extend(metric_lines)
        lines.append("")

    if len(lines) <= 6:
        lines.extend(("### 说明", "", "- 本版本没有需要数据消费方采取额外操作的变化。", ""))

    lines.extend(
        (
            "### 数据边界",
            "",
            "- `dist/data-pipeline/sources/` 提供可公开的来源诊断数据，但不属于 npm 消费接口。",
            "- 原始网页缓存和本机运行状态不属于公开数据集。",
            "",
        )
    )
    content = "\n".join(lines).rstrip() + "\n"
    report: dict[str, object] = {
        "schemaVersion": 2,
        "projectVersion": version,
        "packageVersion": package_version,
        "sources": _source_records((project_changelog, package_changelog, releases_path)),
        "changelogEntries": [asdict(entry) for entry in entries],
        "gitCommits": commit_records,
        "machineReleaseRecord": release_record,
        "structuredEvidence": _structured_evidence(),
        "aggregationPolicy": {
            "internal": "保留 Changelog、数据包发布记录、Git 变更、质量结果和数据审计摘要",
            "public": "只输出用户与数据消费方面向的 RELEASE-NOTES.md",
        },
        "summary": {
            "publicNoteCount": len(notes),
            "changelogEntryCount": len(entries),
            "gitCommitCount": len(commits),
            "publicCommitCount": sum(1 for item in commit_records if item["public"]),
            "omittedInternalCommitCount": sum(1 for item in commit_records if not item["public"]),
            "output": "RELEASE-NOTES.md",
            "outputSha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        },
    }
    return content, report


def main() -> int:
    content, report = build()
    OUTPUT.write_text(content, encoding="utf-8")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[完成] 公开发布摘要：{OUTPUT.relative_to(ROOT)}")
    print(f"[内部聚合报告] {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
