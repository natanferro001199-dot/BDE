"""
Celery tasks for the BDE <-> news-sentiment integration layer.

Add to BDE's celery_app.py beat_schedule:

    "ias-window-check-every-6h": {
        "task": "integration.celery_tasks.check_ias_windows",
        "schedule": crontab(minute=0, hour="*/6"),
    },
    "ingest-tier34-every-6h": {
        "task": "integration.celery_tasks.ingest_tier34_articles",
        "schedule": crontab(minute=30, hour="*/6"),
    },

And add "integration" to autodiscover_tasks in celery_app.py.

Note: remove "ingest-rss-every-6h" from BDE's beat_schedule if you use this —
the two tasks would fetch the same RSS feeds from different angles.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from celery import shared_task
from loguru import logger


@shared_task(name="integration.celery_tasks.check_ias_windows")
def check_ias_windows():
    """
    Check whether active BDE Tier 1-2 hypotheses have started appearing in
    Tier 3-4 financial media (news-sentiment sources).

    If yes, fire a Telegram alert: the IAS window is closing.
    """
    from integration.ias_monitor import WatchedHypothesis, run_check

    hypotheses = _load_tier1_hypotheses()
    if not hypotheses:
        logger.info("IAS window check: no active Tier 1-2 hypotheses to monitor")
        return {"checked": 0, "alerted": []}

    send_fn = _get_telegram_sender()
    alerted = run_check(hypotheses, send_alert_fn=send_fn)

    if alerted:
        logger.warning(f"IAS window closing for: {alerted}")
    else:
        logger.info(
            f"IAS window check: {len(hypotheses)} hypotheses monitored, "
            "none newly in Tier 3-4"
        )
    return {"checked": len(hypotheses), "alerted": alerted}


@shared_task(name="integration.celery_tasks.ingest_tier34_articles")
def ingest_tier34_articles():
    """
    Pull new articles from news-sentiment's SQLite store and feed them into
    BDE's entity resolution pipeline as Tier 3-4 source documents.
    """
    from integration.ns_bridge import fetch_new_articles, mark_ingested, article_count

    counts = article_count()
    logger.info(
        f"Tier 3-4 ingest: {counts['pending_bde']} new articles "
        f"({counts['total']} total in news-sentiment)"
    )

    processed_uids = []
    errors = 0
    for article in fetch_new_articles():
        try:
            _route_to_entity_resolution(article)
            processed_uids.append(article["uid"])
        except Exception as e:
            logger.error(f"Failed to route article {article['uid']!r}: {e}")
            errors += 1

    if processed_uids:
        mark_ingested(processed_uids)

    logger.info(
        f"Ingested {len(processed_uids)} Tier 3-4 articles "
        f"({errors} errors)"
    )
    return {"ingested": len(processed_uids), "errors": errors}


# ---------------------------------------------------------------------------
# Stubs — replace as BDE phases are built
# ---------------------------------------------------------------------------

def _load_tier1_hypotheses():
    """
    Load active Tier 1-2 hypotheses from Neo4j.
    STUB — returns [] until Phase 5 (Hypothesis Engine) is complete.

    Replace with:
        from neo4j import GraphDatabase
        from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
        from integration.ias_monitor import WatchedHypothesis
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as s:
            rows = s.run(
                "MATCH (h:Hypothesis) "
                "WHERE h.ops_score >= 7.0 AND h.status = 'ACTIVE' "
                "AND h.awareness_layer < 4 "
                "RETURN h.id, h.statement, h.keywords, "
                "       h.confidence, h.ops_score, h.awareness_layer"
            )
            return [WatchedHypothesis(**dict(r)) for r in rows]
    """
    return []


def _route_to_entity_resolution(article: dict) -> None:
    """
    Send a Tier 3-4 article through BDE's entity resolution pipeline.
    STUB — logs until Phase 3 (Entity Resolution) is complete.

    Replace with:
        from resolution.resolver import route_document
        route_document(article)
    """
    logger.debug(
        f"[STUB] entity resolution: [{article['source']}] {article['title'][:60]}"
    )


def _get_telegram_sender():
    """
    Return the Telegram send function from news-sentiment's notifier.
    Returns None if tokens are not configured (alerts are logged only).
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        logger.debug("TELEGRAM_BOT_TOKEN/CHAT_ID not set — IAS alerts will be logged only")
        return None
    try:
        ns_src = str(
            Path(__file__).resolve().parents[2] / "news-sentiment" / "src"
        )
        if ns_src not in sys.path:
            sys.path.insert(0, ns_src)
        from news_sentiment.notify.telegram import TelegramNotifier
        return TelegramNotifier(bot_token, chat_id).send
    except Exception as e:
        logger.warning(f"Could not load Telegram notifier: {e} — alerts logged only")
        return None
