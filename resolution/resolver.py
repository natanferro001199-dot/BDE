"""
resolver.py — Main entity resolution loop for Phase 3.

Flow per document:
  1. Pull from Redis bde:entity_resolution_queue
  2. Embed title + excerpt via nomic-embed-text
  3. Cosine similarity against all 300 taxonomy node embeddings (loaded in-memory)
  4. Top-5 candidates:
       score > 0.80  → auto-route (create MENTIONS edge in Neo4j)
       0.55 – 0.80   → Mistral 7B disambiguation
       < 0.55        → Orphan Queue
  5. Store Document node in Neo4j; create MENTIONS edges for resolved nodes
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import numpy as np
import redis
from loguru import logger
from neo4j import GraphDatabase

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import (
    NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD,
    REDIS_URL, SIMILARITY_HIGH, SIMILARITY_LOW,
)
from resolution.embedder import embed, cosine_similarity
from resolution.mistral_disambiguator import disambiguate
from resolution.orphan_queue import OrphanQueue

ENTITY_QUEUE_KEY = "bde:entity_resolution_queue"
LABELS = ["Company", "Material", "Process", "Technology", "Geography", "Regulation", "Equipment"]

_node_index: list[dict] | None = None  # in-memory cache: [{node_id, name, label, embedding, ...}]


# ──────────────────────────────────────────────
# Neo4j helpers
# ──────────────────────────────────────────────

def _get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def load_node_embeddings(driver) -> list[dict]:
    """Load all taxonomy node embeddings into memory. Called once per process."""
    nodes = []
    with driver.session() as session:
        for label in LABELS:
            rows = session.run(
                f"""MATCH (n:{label})
                    WHERE n.embedding IS NOT NULL
                    RETURN n.id AS node_id, n.name AS name, n.description AS description,
                           n.aliases_str AS aliases_str, n.criticality AS criticality,
                           n.embedding AS embedding, '{label}' AS label"""
            ).data()
            nodes.extend(rows)
    logger.info(f"Loaded {len(nodes)} taxonomy node embeddings into memory")
    return nodes


def _ensure_document_schema(driver) -> None:
    with driver.session() as session:
        session.run(
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Document) REQUIRE d.uid IS UNIQUE"
        )


def store_document_node(driver, doc: dict) -> None:
    with driver.session() as session:
        session.run(
            """MERGE (d:Document {uid: $uid})
               SET d.title = $title,
                   d.url = $url,
                   d.source = $source,
                   d.ias_tier = $ias_tier,
                   d.published_at = $published_at,
                   d.ingested_at = $now""",
            uid=doc["uid"],
            title=(doc.get("title") or "")[:512],
            url=doc.get("url") or "",
            source=doc.get("source") or "",
            ias_tier=doc.get("ias_tier") or 2,
            published_at=doc.get("published_at") or "",
            now=datetime.now(timezone.utc).isoformat(),
        )


def create_mention_edge(driver, doc_uid: str, node_id: str, label: str,
                        confidence: float, method: str) -> None:
    with driver.session() as session:
        session.run(
            f"""MATCH (d:Document {{uid: $doc_uid}})
                MATCH (n:{label} {{id: $node_id}})
                MERGE (d)-[r:MENTIONS]->(n)
                SET r.confidence = $confidence,
                    r.method = $method,
                    r.resolved_at = $now""",
            doc_uid=doc_uid,
            node_id=node_id,
            confidence=confidence,
            method=method,
            now=datetime.now(timezone.utc).isoformat(),
        )


# ──────────────────────────────────────────────
# Similarity search
# ──────────────────────────────────────────────

def _top_k_nodes(query_embedding: list[float], nodes: list[dict], k: int = 5) -> list[dict]:
    if not nodes:
        return []
    emb_matrix = np.array([n["embedding"] for n in nodes], dtype=np.float32)
    q = np.array(query_embedding, dtype=np.float32)
    norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-9, norms)
    normed = emb_matrix / norms
    qn = np.linalg.norm(q)
    if qn == 0:
        return []
    scores = normed.dot(q / qn)
    top_idx = np.argsort(scores)[::-1][:k]
    return [
        {**nodes[i], "similarity": float(scores[i])}
        for i in top_idx
        if scores[i] > 0
    ]


# ──────────────────────────────────────────────
# Resolution logic
# ──────────────────────────────────────────────

def _resolve_document(doc: dict, nodes: list[dict], driver, orphan_q: OrphanQueue) -> dict:
    title = doc.get("title") or ""
    text = doc.get("text") or ""
    embed_input = f"{title}. {text[:1500]}"

    query_vec = embed(embed_input)
    candidates = _top_k_nodes(query_vec, nodes, k=10)

    if not candidates:
        orphan_q.add(
            doc_uid=doc["uid"], title=title, text_excerpt=text[:500],
            embedding=query_vec, candidate_entities=doc.get("candidate_entities", []),
            best_match_node=None, best_similarity=0.0, reason="no_candidates",
        )
        return {"uid": doc["uid"], "status": "orphan", "reason": "no_candidates"}

    best = candidates[0]
    best_score = best["similarity"]

    mentions_created = 0

    if best_score >= SIMILARITY_HIGH:
        # Auto-route: all candidates above threshold
        store_document_node(driver, doc)
        for c in candidates:
            if c["similarity"] >= SIMILARITY_HIGH:
                create_mention_edge(driver, doc["uid"], c["node_id"], c["label"],
                                    c["similarity"], "vector_auto")
                mentions_created += 1
        return {"uid": doc["uid"], "status": "auto_routed", "mentions": mentions_created,
                "best": best["node_id"], "score": best_score}

    elif best_score >= SIMILARITY_LOW:
        # Uncertain zone — ask Mistral
        result = disambiguate(title, text[:800], candidates)
        if result:
            node_id = result["node_id"]
            matched = next((c for c in candidates if c["node_id"] == node_id), None)
            if matched:
                store_document_node(driver, doc)
                create_mention_edge(driver, doc["uid"], node_id, matched["label"],
                                    result["confidence"], "mistral")
                return {"uid": doc["uid"], "status": "mistral_routed",
                        "mentions": 1, "best": node_id, "score": result["confidence"]}
        # Mistral undecided
        orphan_q.add(
            doc_uid=doc["uid"], title=title, text_excerpt=text[:500],
            embedding=query_vec, candidate_entities=doc.get("candidate_entities", []),
            best_match_node=best["node_id"], best_similarity=best_score,
            reason="mistral_undecided",
        )
        return {"uid": doc["uid"], "status": "orphan", "reason": "mistral_undecided",
                "best_score": best_score}

    else:
        # Below minimum threshold
        orphan_q.add(
            doc_uid=doc["uid"], title=title, text_excerpt=text[:500],
            embedding=query_vec, candidate_entities=doc.get("candidate_entities", []),
            best_match_node=best["node_id"], best_similarity=best_score,
            reason="below_threshold",
        )
        return {"uid": doc["uid"], "status": "orphan", "reason": "below_threshold",
                "best_score": best_score}


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def resolve_batch(batch_size: int = 20) -> dict:
    global _node_index

    driver = _get_driver()
    r = redis.from_url(REDIS_URL, decode_responses=True)
    orphan_q = OrphanQueue()

    if _node_index is None:
        _node_index = load_node_embeddings(driver)
        _ensure_document_schema(driver)

    if not _node_index:
        logger.error("No taxonomy nodes with embeddings found in Neo4j")
        return {"error": "no_taxonomy_nodes"}

    queue_depth = r.llen(ENTITY_QUEUE_KEY)
    if queue_depth == 0:
        logger.debug("Entity resolution queue is empty")
        return {"processed": 0, "queue_depth": 0}

    items = r.lpop(ENTITY_QUEUE_KEY, batch_size)
    if not items:
        return {"processed": 0, "queue_depth": queue_depth}

    docs = [json.loads(item) for item in items]

    results = {"auto_routed": 0, "mistral_routed": 0, "orphaned": 0, "errors": 0}
    for doc in docs:
        try:
            out = _resolve_document(doc, _node_index, driver, orphan_q)
            status = out.get("status", "error")
            if status == "auto_routed":
                results["auto_routed"] += 1
            elif status == "mistral_routed":
                results["mistral_routed"] += 1
            elif status == "orphan":
                results["orphaned"] += 1
            else:
                results["errors"] += 1
        except Exception as e:
            logger.exception(f"Error resolving {doc.get('uid')}: {e}")
            results["errors"] += 1

    driver.close()
    results["processed"] = len(docs)
    results["queue_remaining"] = r.llen(ENTITY_QUEUE_KEY)
    results["orphan_queue"] = orphan_q.counts()
    logger.info(f"Entity resolution batch: {results}")
    return results


def reload_node_index() -> None:
    """Force reload of in-memory node embeddings (call after taxonomy updates)."""
    global _node_index
    _node_index = None


def stats() -> dict:
    r = redis.from_url(REDIS_URL, decode_responses=True)
    orphan_q = OrphanQueue()
    return {
        "entity_queue_depth": r.llen(ENTITY_QUEUE_KEY),
        "orphan_stats": orphan_q.counts(),
    }


if __name__ == "__main__":
    print(resolve_batch(batch_size=10))
