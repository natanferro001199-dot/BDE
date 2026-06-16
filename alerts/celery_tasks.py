"""
alerts/celery_tasks.py — Celery tasks for BDE alert delivery.

Scheduled tasks:
  - Daily digest:      08:00 UTC every day
  - New Tier-1 check: every 6h (fires once per hypothesis on first crossing OPS >= 0.60)
  - ACH needed check: every 4h (fires once per hypothesis on crossing 0.80 confidence)

Sentinel layer values stored in ias_alerts table to deduplicate:
  layer 98 = "ach review needed" alert sent
  layer 99 = "new tier-1 signal" alert sent
"""
from __future__ import annotations

from celery import shared_task
from loguru import logger


@shared_task(name="alerts.celery_tasks.send_daily_digest")
def send_daily_digest() -> dict:
    from scoring.opportunity_scorer import ranked_opportunities
    from hypotheses.hypothesis_manager import HypothesisManager
    from ingestion.base import IngestStore
    from alerts.telegram import send_daily_digest as _send, is_configured
    from datetime import datetime, timezone

    if not is_configured():
        logger.info("Telegram not configured — skipping daily digest")
        return {"sent": False}

    opps = ranked_opportunities()

    mgr = HypothesisManager()
    all_hyps = mgr.active()
    now = datetime.now(timezone.utc)
    new_this_week = sum(1 for h in all_hyps if _days_since(h.get("created_at", ""), now) <= 7)

    store = IngestStore()
    ingest_count = store.counts().get("total", 0)

    sent = _send(opps, ingest_count, new_this_week)
    logger.info(f"Daily digest {'sent' if sent else 'failed (check Telegram token)'}")
    return {"sent": sent, "opportunities": len(opps)}


@shared_task(name="alerts.celery_tasks.check_new_tier1")
def check_new_tier1() -> dict:
    """Alert the first time each hypothesis crosses OPS >= 0.60 (Tier 1)."""
    from scoring.opportunity_scorer import ranked_opportunities
    from alerts.telegram import alert_new_tier1, is_configured
    from integration.ias_monitor import persist_alert, load_alerted_layers

    if not is_configured():
        return {"checked": 0, "alerted": []}

    tier1 = [o for o in ranked_opportunities() if o.get("tier") == 1]
    alerted = []

    for o in tier1:
        hid = o["id"]
        if 99 in load_alerted_layers(hid):
            continue
        sent = alert_new_tier1(
            node_name=o.get("node_name") or o.get("node_id", ""),
            node_id=o.get("node_id", ""),
            statement=o.get("statement", ""),
            srs_score=o.get("srs_score", 0),
            confidence=o.get("confidence", 0),
            ops_score=o.get("ops_final", 0),
            awareness_layer=o.get("awareness_layer", 1),
            falsification_criteria=o.get("falsification_criteria", []),
        )
        if sent:
            persist_alert(hid, 99)
            alerted.append(hid)

    logger.info(f"New Tier-1 check: {len(tier1)} active, {len(alerted)} newly alerted")
    return {"checked": len(tier1), "alerted": alerted}


@shared_task(name="alerts.celery_tasks.check_ach_needed")
def check_ach_needed() -> dict:
    """Alert the first time a hypothesis crosses 0.80 confidence without ACH review."""
    from hypotheses.hypothesis_manager import HypothesisManager
    from scoring.opportunity_scorer import score_hypothesis
    from alerts.telegram import alert_ach_needed, is_configured
    from integration.ias_monitor import persist_alert, load_alerted_layers

    if not is_configured():
        return {"checked": 0, "alerted": []}

    mgr = HypothesisManager()
    candidates = [
        h for h in mgr.active(min_confidence=0.80)
        if not h.get("ach_reviewed")
    ]
    alerted = []

    for h in candidates:
        hid = h["id"]
        if 98 in load_alerted_layers(hid):
            continue
        scored = score_hypothesis(h)
        sent = alert_ach_needed(
            node_name=h.get("node_name") or h.get("node_id", ""),
            hyp_id=hid,
            confidence=float(h.get("confidence", 0)),
            ops_score=scored["ops_final"],
        )
        if sent:
            persist_alert(hid, 98)
            alerted.append(hid)

    logger.info(f"ACH check: {len(candidates)} need review, {len(alerted)} newly alerted")
    return {"checked": len(candidates), "alerted": alerted}


def _days_since(ts: str, now) -> float:
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (now - dt).days
    except Exception:
        return 999.0
