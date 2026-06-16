"""
evidence_updater.py — When a new document is resolved to a taxonomy node,
update confidence of all active hypotheses linked to that node.

Called by the entity resolver after creating a MENTIONS edge.
Also reads from Neo4j to find linked documents for a hypothesis.
"""
from __future__ import annotations

import json

from loguru import logger
from neo4j import GraphDatabase

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
from hypotheses.hypothesis_manager import HypothesisManager

SUPPLY_CHAIN_RISK_TERMS = [
    "shortage", "delay", "disruption", "bottleneck", "constrained", "sole source",
    "single source", "export control", "ban", "restriction", "sanctions", "tariff",
    "capacity constraint", "lead time", "backlog", "allocation", "rationing",
]

POSITIVE_TERMS = [
    "expansion", "new fab", "alternative supplier", "qualification", "diversif",
    "investment", "capacity increase", "second source", "partnership",
]


def _score_evidence(title: str, text: str) -> float:
    """Returns +1.0 (supports risk) to -1.0 (mitigates risk) based on content."""
    combined = (title + " " + text).lower()
    risk_hits = sum(1 for t in SUPPLY_CHAIN_RISK_TERMS if t in combined)
    positive_hits = sum(1 for t in POSITIVE_TERMS if t in combined)
    net = risk_hits - positive_hits
    return max(-1.0, min(1.0, net / max(1, risk_hits + positive_hits)))


def update_from_document(
    doc_uid: str,
    doc_title: str,
    doc_text: str,
    node_id: str,
) -> list[str]:
    """
    Find all active hypotheses for node_id, add doc as evidence, update confidence.
    Returns list of hypothesis IDs updated.
    """
    mgr = HypothesisManager()
    hypotheses = mgr.for_node(node_id)
    active = [h for h in hypotheses if h["status"] == "active"]

    if not active:
        return []

    sentiment = _score_evidence(doc_title, doc_text)
    supports = sentiment >= 0

    evidence_text = f"[{doc_uid[:12]}] {doc_title[:120]}"
    updated = []
    for h in active:
        mgr.add_evidence(h["id"], evidence_text, supports=supports)
        updated.append(h["id"])
        logger.debug(
            f"Evidence {'supports' if supports else 'challenges'} "
            f"hypothesis {h['id'][:8]}... (sentiment={sentiment:.2f})"
        )

    return updated


def check_ias_windows(mgr: HypothesisManager | None = None) -> list[dict]:
    """
    Returns hypotheses with confidence >= 0.70 that now appear in public media
    (awareness_layer will be updated by integration layer via topic_sync).
    These are 'IAS window closing' signals: internal signal going public.
    """
    if mgr is None:
        mgr = HypothesisManager()
    tier1_active = mgr.active(min_confidence=0.70)
    return [h for h in tier1_active if h.get("awareness_layer", 1) <= 2]


def recent_evidence_for_node(node_id: str, limit: int = 10) -> list[dict]:
    """Fetch recent Document nodes linked to a taxonomy node from Neo4j."""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as s:
        rows = s.run(
            """MATCH (d:Document)-[r:MENTIONS]->(n {id: $node_id})
               RETURN d.uid, d.title, d.source, d.published_at,
                      r.confidence, r.method
               ORDER BY d.published_at DESC LIMIT $limit""",
            node_id=node_id, limit=limit,
        ).data()
    driver.close()
    return rows
