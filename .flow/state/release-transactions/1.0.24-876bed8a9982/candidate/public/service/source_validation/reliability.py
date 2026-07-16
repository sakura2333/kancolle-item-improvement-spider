from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from configs.path import PROJECT_ROOT, get_data_pipeline_dir
from service.source_validation.history import aggregate_source_facts, history_root
from service.source_validation.model import SourceResult
from util.json_utils import read_json_lines, write_json

RELIABILITY_SCHEMA_VERSION = 1
DEFAULT_CONFIG_PATH = Path(PROJECT_ROOT) / "configs" / "source-reliability.json"


def reliability_root() -> Path:
    return Path(get_data_pipeline_dir("sources")) / "reliability"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _source_name(source: str) -> str:
    return source.replace("/", "-").replace("_", "-")


def _signature(fact: dict) -> Tuple[bool, ...]:
    return tuple(bool(value) for value in fact.get("week", []))


def _load_config(path: Optional[Path] = None) -> dict:
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    with open(config_path, "r", encoding="utf-8") as file:
        config = json.load(file)
    if config.get("applyToCanonicalElection") is not False:
        raise ValueError("source reliability must remain advisory")
    return config


def _fact_indexes(results: Sequence[SourceResult]) -> Dict[str, Dict[str, dict]]:
    indexes: Dict[str, Dict[str, dict]] = {}
    for result in results:
        if result.status != "ok":
            continue
        facts = aggregate_source_facts(result)
        indexes[result.source] = {fact["factKey"]: fact for fact in facts}
    return indexes


def _pairwise_metrics(source: str, indexes: Mapping[str, Mapping[str, dict]]) -> dict:
    own = indexes[source]
    comparable = 0
    agreements = 0
    by_peer: List[dict] = []
    for peer, peer_index in sorted(indexes.items()):
        if peer == source:
            continue
        overlap = sorted(set(own) & set(peer_index))
        agreed = sum(_signature(own[key]) == _signature(peer_index[key]) for key in overlap)
        comparable += len(overlap)
        agreements += agreed
        by_peer.append({
            "source": peer,
            "comparableCount": len(overlap),
            "agreementCount": agreed,
            "agreementRate": round(agreed / len(overlap), 6) if overlap else None,
        })
    return {
        "comparableCount": comparable,
        "agreementCount": agreements,
        "agreementRate": round(agreements / comparable, 6) if comparable else None,
        "byPeer": by_peer,
    }


def _peer_consensus_metrics(source: str, indexes: Mapping[str, Mapping[str, dict]]) -> dict:
    own = indexes[source]
    peers = {name: index for name, index in indexes.items() if name != source}
    comparable = 0
    agreements = 0

    for key, own_fact in own.items():
        signatures: Counter[Tuple[bool, ...]] = Counter(
            _signature(index[key])
            for index in peers.values()
            if key in index
        )
        if not signatures:
            continue
        consensus, count = signatures.most_common(1)[0]
        if count < 2:
            continue
        comparable += 1
        if _signature(own_fact) == consensus:
            agreements += 1

    return {
        "comparableCount": comparable,
        "agreementCount": agreements,
        "agreementRate": round(agreements / comparable, 6) if comparable else None,
    }


def _history_metrics(source: str, root: Path) -> dict:
    path = root / "changes" / f"{_source_name(source)}.nedb"
    events = [row for row in read_json_lines(path) if isinstance(row, dict)]
    counts = Counter(str(event.get("changeType", "unknown")) for event in events)
    assessments = Counter(str(event.get("peerAssessment", "unconfirmed")) for event in events)
    evaluable = assessments["corroborated"] + assessments["outlier"]
    return {
        "eventCount": len(events),
        "addedCount": counts["added"],
        "removedCount": counts["removed"],
        "modifiedCount": counts["modified"],
        "reappearedCount": counts["reappeared"],
        "corroboratedCount": assessments["corroborated"],
        "outlierCount": assessments["outlier"],
        "unconfirmedCount": assessments["unconfirmed"],
        "evaluableCount": evaluable,
        "corroborationRate": round(assessments["corroborated"] / evaluable, 6) if evaluable else None,
    }


def _weighted_average(values: List[Tuple[Optional[float], float]]) -> Optional[float]:
    available = [(value, weight) for value, weight in values if value is not None and weight > 0]
    if not available:
        return None
    total = sum(weight for _, weight in available)
    return sum(float(value) * weight for value, weight in available) / total


def _confidence_label(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def calculate_source_reliability(
    results: Sequence[SourceResult],
    *,
    history_dir: Optional[Path] = None,
    config_path: Optional[Path] = None,
    generated_at: Optional[str] = None,
) -> dict:
    config = _load_config(config_path)
    indexes = _fact_indexes(results)
    history_dir = Path(history_dir) if history_dir is not None else history_root()
    generated_at = generated_at or _now_iso()

    current_weights = config["currentSignals"]
    history_contribution = float(config["historyContribution"])
    minimum_history = int(config["minimumHistoricalEvaluableChanges"])
    min_weight, max_weight = [float(value) for value in config["relativeWeightRange"]]

    rows: List[dict] = []
    eligible_scores: Dict[str, float] = {}
    for source in sorted(indexes):
        pairwise = _pairwise_metrics(source, indexes)
        peer_consensus = _peer_consensus_metrics(source, indexes)
        history = _history_metrics(source, history_dir)
        current_score = _weighted_average([
            (pairwise["agreementRate"], float(current_weights["pairwiseAgreement"])),
            (peer_consensus["agreementRate"], float(current_weights["peerConsensusAgreement"])),
        ])
        history_rate = history["corroborationRate"]
        if current_score is not None and history_rate is not None and history["evaluableCount"] >= minimum_history:
            combined_score = current_score * (1.0 - history_contribution) + history_rate * history_contribution
            history_applied = True
        else:
            combined_score = current_score
            history_applied = False

        pair_confidence = min(
            1.0,
            pairwise["comparableCount"] / max(1, int(config["minimumPairwiseEvidenceForFullConfidence"])),
        )
        peer_confidence = min(
            1.0,
            peer_consensus["comparableCount"] / max(1, int(config["minimumPeerConsensusEvidenceForFullConfidence"])),
        )
        history_confidence = min(
            1.0,
            history["evaluableCount"] / max(1, int(config["minimumHistoricalEvidenceForFullConfidence"])),
        )
        confidence_score = round(
            0.45 * pair_confidence + 0.30 * peer_confidence + 0.25 * history_confidence,
            6,
        )

        row = {
            "source": source,
            "factCount": len(indexes[source]),
            "pairwise": pairwise,
            "peerConsensus": peer_consensus,
            "history": history,
            "currentConsistencyScore": round(current_score, 6) if current_score is not None else None,
            "historyAppliedToWeight": history_applied,
            "combinedScore": round(combined_score, 6) if combined_score is not None else None,
            "confidenceScore": confidence_score,
            "confidence": _confidence_label(confidence_score),
        }
        rows.append(row)
        if combined_score is not None:
            eligible_scores[source] = combined_score

    mean_score = (
        sum(eligible_scores.values()) / len(eligible_scores)
        if eligible_scores else 1.0
    )
    for row in rows:
        score = eligible_scores.get(row["source"])
        if score is None or mean_score <= 0:
            row["relativeWeight"] = 1.0
            row["weightStatus"] = "insufficient-evidence"
        else:
            relative = max(min_weight, min(max_weight, score / mean_score))
            row["relativeWeight"] = round(relative, 4)
            row["weightStatus"] = "advisory"

    return {
        "schemaVersion": RELIABILITY_SCHEMA_VERSION,
        "generatedAt": generated_at,
        "mode": config["mode"],
        "applyToCanonicalElection": False,
        "canonicalElectionUnchanged": True,
        "methodology": {
            "currentSignals": current_weights,
            "historyContribution": history_contribution,
            "minimumHistoricalEvaluableChanges": minimum_history,
            "relativeWeightRange": [min_weight, max_weight],
            "note": "Weights measure relative consistency and corroboration, not truth or authority.",
        },
        "sources": rows,
    }


def export_source_reliability(
    results: Sequence[SourceResult],
    *,
    output_dir: Optional[Path] = None,
    history_dir: Optional[Path] = None,
    config_path: Optional[Path] = None,
    generated_at: Optional[str] = None,
) -> dict:
    output_dir = Path(output_dir) if output_dir is not None else reliability_root()
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = calculate_source_reliability(
        results,
        history_dir=history_dir,
        config_path=config_path,
        generated_at=generated_at,
    )
    write_json(output_dir / "summary.json", payload, mode="w", log=False)

    lines = [
        "# Source reliability observation",
        "",
        f"Generated: {payload['generatedAt']}",
        "",
        "These weights are advisory relative-consistency signals. They do not select or overwrite the canonical dataset.",
        "",
        "| Source | Facts | Pairwise | Peer consensus | History corroboration | Relative weight | Confidence |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["sources"]:
        pair = row["pairwise"]["agreementRate"]
        peer = row["peerConsensus"]["agreementRate"]
        history = row["history"]["corroborationRate"]
        lines.append(
            "| {source} | {facts} | {pair} | {peer} | {history} | {weight:.4f} | {confidence} |".format(
                source=row["source"],
                facts=row["factCount"],
                pair="-" if pair is None else f"{pair:.2%}",
                peer="-" if peer is None else f"{peer:.2%}",
                history="-" if history is None else f"{history:.2%}",
                weight=row["relativeWeight"],
                confidence=row["confidence"],
            )
        )
    lines.extend([
        "",
        "- Pairwise agreement compares facts present in both sources.",
        "- Peer consensus only evaluates a source when at least two other sources agree.",
        "- Historical corroboration starts affecting the weight only after the configured minimum evidence count.",
        "- Missing coverage is reported separately and is not treated as a false fact.",
        "",
    ])
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return payload
