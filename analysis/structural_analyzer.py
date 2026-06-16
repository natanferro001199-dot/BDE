"""
structural_analyzer.py — Phase 4: Discovers bottleneck candidates via graph topology.

Metrics computed on the BDE taxonomy graph in Neo4j:
  - Betweenness centrality  (how many shortest paths pass through a node)
  - Articulation point detection (removal disconnects the supply graph)
  - Supplier concentration  = 1 - (1 / num_qualified_suppliers)
  - SRS (Supply Risk Score) = centrality × concentration × criticality_weight

Writes SRS scores back to Neo4j as node property `srs_score` and
emits a ranked report so Phase 5 can generate hypotheses from the top nodes.

Run weekly via Celery beat: analysis.celery_tasks.run_structural_analysis
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from datetime import datetime, timezone

from loguru import logger
from neo4j import GraphDatabase

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

LABELS = ["Company", "Material", "Process", "Technology", "Geography", "Regulation", "Equipment"]
REL_TYPES = ["PRODUCES", "DEPENDS_ON", "COMPETES_WITH", "REGULATES",
             "SUBSTITUTES_FOR", "ENABLES", "CONTROLS", "LOCATED_IN", "USES", "MANUFACTURES"]

TOP_N = 20  # nodes to surface in report


# ──────────────────────────────────────────────────────
# Graph loading
# ──────────────────────────────────────────────────────

def _load_graph(driver) -> tuple[list[dict], list[tuple[str, str]]]:
    """Return (nodes, edges) where edges are (src_id, tgt_id) pairs."""
    nodes, edges = [], []

    with driver.session() as s:
        for label in LABELS:
            rows = s.run(
                f"MATCH (n:{label}) RETURN n.id AS id, n.name AS name, "
                f"n.criticality AS criticality, '{label}' AS label"
            ).data()
            nodes.extend(rows)

        rel_filter = "|".join(REL_TYPES)
        rows = s.run(
            f"MATCH (a)-[r:{rel_filter}]->(b) "
            "WHERE a.id IS NOT NULL AND b.id IS NOT NULL "
            "RETURN a.id AS src, b.id AS tgt"
        ).data()
        edges = [(r["src"], r["tgt"]) for r in rows]

    return nodes, edges


def _build_adjacency(nodes: list[dict], edges: list[tuple[str, str]]):
    """Build undirected adjacency list (for centrality/articulation)
       and directed suppliers map (for concentration)."""
    node_ids = {n["id"] for n in nodes}
    adj: dict[str, set[str]] = defaultdict(set)
    suppliers: dict[str, set[str]] = defaultdict(set)  # tgt → srcs

    for src, tgt in edges:
        if src in node_ids and tgt in node_ids:
            adj[src].add(tgt)
            adj[tgt].add(src)
            suppliers[tgt].add(src)

    return adj, suppliers


# ──────────────────────────────────────────────────────
# Betweenness centrality (Brandes algorithm, unweighted)
# ──────────────────────────────────────────────────────

def _betweenness_centrality(nodes: list[dict], adj: dict[str, set[str]]) -> dict[str, float]:
    node_ids = [n["id"] for n in nodes]
    cb: dict[str, float] = {nid: 0.0 for nid in node_ids}

    for s in node_ids:
        stack: list[str] = []
        pred: dict[str, list[str]] = {nid: [] for nid in node_ids}
        sigma: dict[str, float] = {nid: 0.0 for nid in node_ids}
        sigma[s] = 1.0
        dist: dict[str, int] = {nid: -1 for nid in node_ids}
        dist[s] = 0
        queue: deque[str] = deque([s])

        while queue:
            v = queue.popleft()
            stack.append(v)
            for w in adj.get(v, set()):
                if dist[w] < 0:
                    queue.append(w)
                    dist[w] = dist[v] + 1
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)

        delta: dict[str, float] = {nid: 0.0 for nid in node_ids}
        while stack:
            w = stack.pop()
            for v in pred[w]:
                if sigma[w] > 0:
                    delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                cb[w] += delta[w]

    n = len(node_ids)
    norm = (n - 1) * (n - 2) if n > 2 else 1.0
    return {k: v / norm for k, v in cb.items()}


# ──────────────────────────────────────────────────────
# Articulation points (Tarjan's algorithm)
# ──────────────────────────────────────────────────────

def _articulation_points(node_ids: list[str], adj: dict[str, set[str]]) -> set[str]:
    visited: dict[str, bool] = {nid: False for nid in node_ids}
    disc: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {nid: None for nid in node_ids}
    aps: set[str] = set()
    timer = [0]

    def dfs(u: str) -> None:
        children = 0
        visited[u] = True
        disc[u] = low[u] = timer[0]
        timer[0] += 1
        for v in adj.get(u, set()):
            if not visited[v]:
                children += 1
                parent[v] = u
                dfs(v)
                low[u] = min(low[u], low[v])
                if parent[u] is None and children > 1:
                    aps.add(u)
                if parent[u] is not None and low[v] >= disc[u]:
                    aps.add(u)
            elif v != parent[u]:
                low[u] = min(low[u], disc[v])

    for nid in node_ids:
        if not visited[nid]:
            dfs(nid)

    return aps


# ──────────────────────────────────────────────────────
# SRS scoring
# ──────────────────────────────────────────────────────

def _compute_srs(
    nodes: list[dict],
    centrality: dict[str, float],
    suppliers: dict[str, set[str]],
    aps: set[str],
) -> list[dict]:
    results = []
    for node in nodes:
        nid = node["id"]
        c = centrality.get(nid, 0.0)

        num_suppliers = max(1, len(suppliers.get(nid, set())))
        concentration = 1.0 - (1.0 / num_suppliers)

        criticality = float(node.get("criticality") or 0.5)

        ap_bonus = 0.20 if nid in aps else 0.0
        srs = (c * 0.40 + concentration * 0.35 + criticality * 0.25) + ap_bonus

        results.append({
            "node_id": nid,
            "name": node.get("name", ""),
            "label": node.get("label", ""),
            "srs_score": round(min(srs, 1.0), 4),
            "betweenness": round(c, 4),
            "concentration": round(concentration, 4),
            "criticality": round(criticality, 4),
            "num_suppliers": num_suppliers,
            "is_articulation_point": nid in aps,
        })

    results.sort(key=lambda x: x["srs_score"], reverse=True)
    return results


# ──────────────────────────────────────────────────────
# Write scores back to Neo4j
# ──────────────────────────────────────────────────────

def _write_scores(driver, scored: list[dict]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with driver.session() as s:
        for label in LABELS:
            label_nodes = [n for n in scored if n["label"] == label]
            if not label_nodes:
                continue
            s.run(
                f"""UNWIND $nodes AS n
                    MATCH (x:{label} {{id: n.node_id}})
                    SET x.srs_score = n.srs_score,
                        x.betweenness = n.betweenness,
                        x.concentration = n.concentration,
                        x.is_articulation_point = n.is_articulation_point,
                        x.srs_updated_at = $now""",
                nodes=label_nodes, now=now,
            )
    logger.info(f"Wrote SRS scores to {len(scored)} Neo4j nodes")


# ──────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────

def run() -> dict:
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        logger.info("Loading supply chain graph from Neo4j...")
        nodes, edges = _load_graph(driver)
        logger.info(f"Graph: {len(nodes)} nodes, {len(edges)} edges")

        adj, suppliers = _build_adjacency(nodes, edges)
        node_ids = [n["id"] for n in nodes]

        logger.info("Computing betweenness centrality...")
        centrality = _betweenness_centrality(nodes, adj)

        logger.info("Finding articulation points...")
        aps = _articulation_points(node_ids, adj)
        logger.info(f"Found {len(aps)} articulation points")

        scored = _compute_srs(nodes, centrality, suppliers, aps)
        _write_scores(driver, scored)

        top = scored[:TOP_N]
        logger.info(f"Top-{TOP_N} bottleneck candidates by SRS:")
        for i, n in enumerate(top[:10], 1):
            ap = "*AP" if n["is_articulation_point"] else "   "
            logger.info(
                f"  {i:2}. {ap} {n['srs_score']:.3f} [{n['label'][:4]}] {n['name']}"
            )

        return {
            "nodes_analyzed": len(nodes),
            "edges_analyzed": len(edges),
            "articulation_points": len(aps),
            "top_20": top,
            "run_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        driver.close()


def top_bottlenecks(n: int = 20) -> list[dict]:
    """Return top-n nodes by SRS score (reads from stored property, no recompute)."""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    results = []
    with driver.session() as s:
        for label in LABELS:
            rows = s.run(
                f"""MATCH (n:{label})
                    WHERE n.srs_score IS NOT NULL
                    RETURN n.id AS node_id, n.name AS name, '{label}' AS label,
                           n.srs_score AS srs_score, n.betweenness AS betweenness,
                           n.concentration AS concentration, n.criticality AS criticality,
                           n.is_articulation_point AS is_articulation_point"""
            ).data()
            results.extend(rows)
    driver.close()
    results.sort(key=lambda x: x.get("srs_score") or 0, reverse=True)
    return results[:n]


def run_whatif(excluded_node_id: str) -> dict:
    """
    Simulate removing one node from the supply chain and re-compute SRS for all
    remaining nodes. Reads from Neo4j but does NOT write results back.
    """
    import sys
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 2000))

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        # Snapshot current stored SRS scores before simulation
        original: dict[str, dict] = {}
        with driver.session() as s:
            for label in LABELS:
                rows = s.run(
                    f"""MATCH (n:{label})
                        WHERE n.srs_score IS NOT NULL
                        RETURN n.id AS node_id, n.name AS name, '{label}' AS label,
                               n.srs_score AS srs_score,
                               coalesce(n.is_articulation_point, false) AS was_ap""",
                ).data()
                for r in rows:
                    original[r["node_id"]] = dict(r)

        nodes_all, edges_all = _load_graph(driver)
        ex = excluded_node_id
        nodes  = [n for n in nodes_all if n["id"] != ex]
        edges  = [(s, t) for s, t in edges_all if s != ex and t != ex]
        excl_name = next((n.get("name", ex) for n in nodes_all if n["id"] == ex), ex)

        if not nodes:
            return {"error": "No nodes remaining after exclusion", "excluded_name": excl_name}

        adj, suppliers = _build_adjacency(nodes, edges)
        node_ids  = [n["id"] for n in nodes]
        centrality = _betweenness_centrality(nodes, adj)
        aps        = _articulation_points(node_ids, adj)
        new_scored = _compute_srs(nodes, centrality, suppliers, aps)
        new_by_id  = {r["node_id"]: r for r in new_scored}

        comparison = []
        for nid, orig in original.items():
            if nid == ex:
                continue
            new = new_by_id.get(nid)
            if new:
                old_srs = float(orig.get("srs_score") or 0)
                new_srs = float(new["srs_score"])
                comparison.append({
                    "node_id":   nid,
                    "name":      orig.get("name", ""),
                    "label":     orig.get("label", ""),
                    "srs_before": round(old_srs, 4),
                    "srs_after":  round(new_srs, 4),
                    "delta":      round(new_srs - old_srs, 4),
                    "was_ap":     bool(orig.get("was_ap", False)),
                    "now_ap":     nid in aps,
                })

        comparison.sort(key=lambda x: abs(x["delta"]), reverse=True)

        before_total = sum(float(o.get("srs_score") or 0) for nid, o in original.items() if nid != ex)
        after_total  = sum(r["srs_score"] for r in new_scored)
        old_ap_count = sum(1 for nid, o in original.items() if nid != ex and o.get("was_ap"))

        return {
            "excluded_id":     ex,
            "excluded_name":   excl_name,
            "nodes_remaining": len(nodes),
            "new_ap_count":    len(aps),
            "old_ap_count":    old_ap_count,
            "total_srs_delta": round(after_total - before_total, 4),
            "comparison":      comparison[:30],
        }
    finally:
        driver.close()


if __name__ == "__main__":
    import json
    result = run()
    print(f"\nNodes analyzed: {result['nodes_analyzed']}")
    print(f"Edges analyzed: {result['edges_analyzed']}")
    print(f"Articulation points: {result['articulation_points']}")
    print(f"\nTop-20 Bottleneck Candidates (SRS Score):")
    print(f"{'Rank':<5} {'AP':3} {'SRS':6} {'Label':<12} {'Name'}")
    print("-" * 60)
    for i, n in enumerate(result["top_20"], 1):
        ap = "*AP" if n["is_articulation_point"] else "   "
        print(f"{i:<5} {ap:<4} {n['srs_score']:<6.3f} {n['label']:<12} {n['name']}")
