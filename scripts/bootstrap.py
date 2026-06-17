"""
bootstrap.py — One-shot pipeline seeder.

Runs the full pipeline immediately to populate evidence from existing data:
  1. RSS ingest (fetch latest articles)
  2. Document processor (push articles to entity resolution queue)
  3. Entity resolver (create MENTIONS edges in Neo4j + update evidence inline)
  4. Evidence catch-up (reconcile any MENTIONS edges not yet in evidence)

Run this once after first setup, or any time the evidence table is empty.
Neo4j, Redis (Memurai), and Ollama must be running before starting this script.

Usage:
  cd C:\\Users\\Nataniel\\Documents\\news-sentiment\\BDE
  .venv\\Scripts\\python.exe scripts\\bootstrap.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def step(label: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")


def main() -> None:
    # ── Step 1: RSS ingest ────────────────────────────────────────
    step("Step 1/4: RSS ingest")
    try:
        from ingestion.rss_ingestor import run as rss_run
        result = rss_run()
        print(f"  RSS done: {result}")
    except Exception as e:
        print(f"  RSS failed (continuing): {e}")

    time.sleep(2)

    # ── Step 2: Document processor ────────────────────────────────
    step("Step 2/4: Document processor (push to entity resolution queue)")
    try:
        from processing.document_processor import process_pending
        result = process_pending(limit=500)
        print(f"  Processor done: {result}")
    except Exception as e:
        print(f"  Processor failed (continuing): {e}")

    time.sleep(2)

    # ── Step 3: Entity resolver ────────────────────────────────────
    step("Step 3/4: Entity resolver (create MENTIONS edges + evidence inline)")
    try:
        from resolution.resolver import resolve_batch
        total_resolved = 0
        for _i in range(20):  # drain up to 20 batches of 30
            r = resolve_batch(batch_size=30)
            processed = r.get("processed", 0)
            total_resolved += processed
            print(f"    Batch: {r}")
            if processed == 0 or r.get("queue_remaining", 0) == 0:
                break
            time.sleep(1)
        print(f"  Resolver done: {total_resolved} documents resolved")
    except Exception as e:
        print(f"  Resolver failed (continuing): {e}")

    time.sleep(2)

    # ── Step 4: Evidence catch-up ──────────────────────────────────
    step("Step 4/4: Evidence catch-up (reconcile existing MENTIONS → hypothesis evidence)")
    try:
        from neo4j import GraphDatabase
        from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
        from hypotheses.hypothesis_manager import HypothesisManager
        from hypotheses.evidence_updater import update_from_document
        import json

        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        mgr = HypothesisManager()

        with driver.session() as s:
            rows = s.run("""
                MATCH (d:Document)-[r:MENTIONS]->(n)
                RETURN d.uid AS uid, d.title AS title, n.id AS node_id
                ORDER BY d.published_at DESC
                LIMIT 2000
            """).data()
        driver.close()

        print(f"  Found {len(rows)} MENTIONS edges in Neo4j")

        all_hyps = {h["id"]: h for h in mgr.active()}
        already: dict[str, set[str]] = {}
        for h in all_hyps.values():
            ev = json.loads(h.get("evidence_for") or "[]") + json.loads(h.get("evidence_against") or "[]")
            already[h["id"]] = {e[:14] for e in ev}

        updated = 0
        for row in rows:
            uid = row["uid"] or ""
            prefix = f"[{uid[:12]}]"
            node_id = row["node_id"]
            for h in mgr.for_node(node_id):
                if h["status"] != "active":
                    continue
                if prefix in already.get(h["id"], set()):
                    continue
                update_from_document(
                    doc_uid=uid,
                    doc_title=row.get("title") or "",
                    doc_text="",
                    node_id=node_id,
                )
                already.setdefault(h["id"], set()).add(prefix)
                updated += 1

        print(f"  Evidence catch-up done: {updated} records updated")
    except Exception as e:
        print(f"  Evidence catch-up failed: {e}")

    # ── Summary ────────────────────────────────────────────────────
    step("Done — open http://localhost:8501 and refresh the dashboard")
    try:
        from hypotheses.hypothesis_manager import HypothesisManager
        import json
        mgr = HypothesisManager()
        for h in mgr.active():
            ef = json.loads(h.get("evidence_for") or "[]")
            ea = json.loads(h.get("evidence_against") or "[]")
            print(f"  {h['id'][:8]}  {h['node_name']:<20}  "
                  f"conf={h['confidence']:.2f}  "
                  f"evidence_for={len(ef)}  evidence_against={len(ea)}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
