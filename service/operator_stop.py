from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, TextIO

ANSI_RED = "\033[31m"
ANSI_RESET = "\033[0m"
DEFAULT_EXIT_CODE = 75


@dataclass
class OperatorStopError(RuntimeError):
    """A non-recoverable condition that requires an operator decision.

    The exception is deliberately machine-readable and carries the checkpoint
    that remains safe to reuse after the problem is fixed.
    """

    stop_reason: str
    message: str
    action: str
    checkpoint: str
    details: dict[str, Any] = field(default_factory=dict)
    exit_code: int = DEFAULT_EXIT_CODE

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.message)
        if not self.stop_reason or not self.stop_reason.strip():
            raise ValueError("stop_reason must be non-empty")
        if self.exit_code == 0:
            raise ValueError("operator stop exit_code must be non-zero")

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "operator-stop",
            "stopReason": self.stop_reason,
            "message": self.message,
            "action": self.action,
            "checkpoint": self.checkpoint,
            "exitCode": self.exit_code,
        }
        if self.details:
            payload["details"] = self.details
        return payload


def _stop_identity(error: OperatorStopError) -> str:
    payload = error.to_json()
    return json.dumps(
        {
            "stopReason": payload.get("stopReason"),
            "message": payload.get("message"),
            "action": payload.get("action"),
            "checkpoint": payload.get("checkpoint"),
            "details": payload.get("details", {}),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def dedupe_operator_stops(
    errors: Iterable[OperatorStopError],
) -> list[OperatorStopError]:
    result: list[OperatorStopError] = []
    seen: set[str] = set()
    for error in errors:
        identity = _stop_identity(error)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(error)
    return result


def _stop_summary(error: OperatorStopError) -> dict[str, Any]:
    details = error.details if isinstance(error.details, dict) else {}
    reference = details.get("reference") if isinstance(details.get("reference"), dict) else {}
    result: dict[str, Any] = {
        "stopReason": error.stop_reason,
        "message": error.message,
    }
    for key in ("equipmentId", "equipmentName", "sourceUrl", "methodIndex"):
        if details.get(key) is not None:
            result[key] = details[key]
    for key in (
        "rawName",
        "linkTarget",
        "candidateShipIds",
        "candidateShipNames",
        "candidateShips",
        "canonicalShipId",
        "canonicalShipName",
        "linkTextShipId",
        "linkTextShipName",
        "linkTextStart2Ship",
        "start2Ship",
        "shipPageCrossValidation",
        "questKey",
        "questCode",
        "questName",
    ):
        if reference.get(key) is not None:
            result[key] = reference[key]
    return result


def write_operator_stop_files(
    errors: Iterable[OperatorStopError],
    *,
    output_dir: Path,
) -> tuple[OperatorStopError | None, list[OperatorStopError]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    primary_path = output_dir / "operator-stop.json"
    all_path = output_dir / "operator-stops.nedb"
    unique = dedupe_operator_stops(errors)
    if not unique:
        primary_path.unlink(missing_ok=True)
        all_path.unlink(missing_ok=True)
        return None, []

    summaries = [_stop_summary(error) for error in unique]
    all_path.write_text(
        "".join(
            json.dumps(error.to_json(), ensure_ascii=False, sort_keys=True) + "\n"
            for error in unique
        ),
        encoding="utf-8",
    )
    primary = unique[0]
    primary.details = {
        **primary.details,
        "operatorStopCount": len(unique),
        "operatorStopPath": str(primary_path),
        "operatorStopsPath": str(all_path),
        "operatorStops": summaries,
    }
    primary_path.write_text(
        json.dumps(primary.to_json(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return primary, unique


def write_operator_stop(
    error: OperatorStopError,
    *,
    stream: TextIO = sys.stderr,
    json_path: Path | None = None,
    color: bool | None = None,
) -> None:
    payload = error.to_json()
    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    use_color = stream.isatty() if color is None else bool(color)
    prefix = f"{ANSI_RED}ERROR{ANSI_RESET}" if use_color else "ERROR"
    print(f"{prefix}: {error.message}", file=stream)
    print(f"stopReason: {error.stop_reason}", file=stream)
    print(f"人工处理: {error.action}", file=stream)
    print(f"可继续断点: {error.checkpoint}", file=stream)
    summaries = error.details.get("operatorStops") if isinstance(error.details, dict) else None
    if isinstance(summaries, list):
        print(f"停止项: {len(summaries)}", file=stream)
        for index, summary in enumerate(summaries, 1):
            if not isinstance(summary, dict):
                continue
            equipment = ""
            if summary.get("equipmentId") is not None:
                equipment = f" equipment={summary.get('equipmentId')}:{summary.get('equipmentName') or ''}"
            source = f" source={summary.get('sourceUrl')}" if summary.get("sourceUrl") else ""
            raw_name = f" rawName={summary.get('rawName')}" if summary.get("rawName") else ""
            link_target = f" linkTarget={summary.get('linkTarget')}" if summary.get("linkTarget") else ""
            canonical = ""
            if summary.get("canonicalShipId") is not None:
                canonical = f" canonicalStart2={summary.get('canonicalShipId')}:{summary.get('canonicalShipName') or ''}"
            candidate_ships = summary.get("candidateShips") if isinstance(summary.get("candidateShips"), list) else []
            candidates = ""
            if candidate_ships:
                candidates = " candidates=" + ",".join(
                    f"{ship.get('shipId')}:{ship.get('shipName') or ''}"
                    for ship in candidate_ships
                    if isinstance(ship, dict)
                )
            elif summary.get("candidateShipIds"):
                candidates = " candidateShipIds=" + ",".join(str(value) for value in summary.get("candidateShipIds") or [])
            cross = summary.get("shipPageCrossValidation") if isinstance(summary.get("shipPageCrossValidation"), dict) else {}
            cross_text = ""
            if cross:
                selected = cross.get("selectedShip") if isinstance(cross.get("selectedShip"), dict) else None
                selected_text = ""
                if selected:
                    selected_text = f" selected={selected.get('shipId')}:{selected.get('shipName') or ''}"
                cross_text = f" crossValidation={cross.get('status')}:{cross.get('reason')}{selected_text}"
            print(
                f"  {index}. stopReason={summary.get('stopReason')}"
                f"{equipment}{raw_name}{link_target}{canonical}{candidates}{cross_text}{source}",
                file=stream,
            )
    if error.details:
        detail_payload = dict(error.details)
        detail_payload.pop("operatorStops", None)
        print(
            "details: " + json.dumps(detail_payload, ensure_ascii=False, sort_keys=True),
            file=stream,
        )
