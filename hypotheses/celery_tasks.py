"""Celery tasks for Phase 5 hypothesis engine."""
from celery import shared_task
from loguru import logger


@shared_task(bind=True, max_retries=1, default_retry_delay=60,
             name="hypotheses.celery_tasks.run_evidence_update")
def run_evidence_update(self) -> dict:
    """
    Catch-up scan: find all Document-[MENTIONS]->Node edges in Neo4j that have
    not yet been recorded as hypothesis evidence, then update confidence scores.
    Runs every 2h so missed inline calls are always reconciled.
    """
    try:
        from neo4j import GraphDatabase
        from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
        from hypotheses.hypothesis_manager import HypothesisManager
        from hypotheses.evidence_updater import update_from_document
        import json

        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        mgr = HypothesisManager()

        # Pull all MENTIONS edges with document content (last 30 days)
        with driver.session() as s:
            rows = s.run("""
                MATCH (d:Document)-[r:MENTIONS]->(n)
                WHERE d.published_at >= datetime() - duration('P30D')
                RETURN d.uid AS uid, d.title AS title, n.id AS node_id
                ORDER BY d.published_at DESC
                LIMIT 2000
            """).data()
        driver.close()

        if not rows:
            logger.info("[evidence_update] No MENTIONS edges found in Neo4j")
            return {"scanned": 0, "updated": 0}

        # Build a set of evidence prefixes already recorded
        all_hyps = {h["id"]: h for h in mgr.active()}
        already_recorded: dict[str, set[str]] = {}
        for h in all_hyps.values():
            ev = json.loads(h.get("evidence_for") or "[]") + json.loads(h.get("evidence_against") or "[]")
            already_recorded[h["id"]] = {e[:14] for e in ev}  # "[uid12chars]" = 14 chars

        updated_total = 0
        for row in rows:
            uid = row["uid"] or ""
            prefix = f"[{uid[:12]}]"
            node_id = row["node_id"]
            hypotheses = mgr.for_node(node_id)
            for h in hypotheses:
                if h["status"] != "active":
                    continue
                if prefix in already_recorded.get(h["id"], set()):
                    continue
                update_from_document(
                    doc_uid=uid,
                    doc_title=row.get("title") or "",
                    doc_text="",
                    node_id=node_id,
                )
                already_recorded.setdefault(h["id"], set()).add(prefix)
                updated_total += 1

        logger.info(f"[evidence_update] Scanned {len(rows)} edges, updated {updated_total} hypothesis records")
        return {"scanned": len(rows), "updated": updated_total}
    except Exception as exc:
        logger.exception(f"[evidence_update] Failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=1, default_retry_delay=300,
             name="hypotheses.celery_tasks.run_hypothesis_generator")
def run_hypothesis_generator(self, top_n: int = 10) -> dict:
    try:
        from hypotheses.hypothesis_generator import run
        result = run(top_n=top_n)
        logger.info(f"[Celery] Hypothesis generator: {result}")
        return result
    except Exception as exc:
        logger.exception(f"[Celery] Hypothesis generator failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=60,
             name="hypotheses.celery_tasks.check_ias_windows")
def check_ias_windows_task(self) -> dict:
    try:
        from hypotheses.evidence_updater import check_ias_windows
        windows = check_ias_windows()
        logger.info(f"[Celery] IAS windows check: {len(windows)} hypotheses at risk of going public")
        return {"ias_windows": len(windows), "ids": [h["id"] for h in windows]}
    except Exception as exc:
        logger.warning(f"[Celery] IAS check failed: {exc}")
        raise self.retry(exc=exc)
