"""
alerts/telegram.py — BDE Telegram notification system.

All alert types in one place, using the Telegram Bot API directly.
No dependency on the news-sentiment project.

Setup (one-time):
  1. Message @BotFather on Telegram → /newbot → copy the token
  2. Message @userinfobot on Telegram → copy your chat_id (looks like 123456789)
  3. Add to .env:
       TELEGRAM_BOT_TOKEN=123456789:ABCDefGHIjklMNOpQRSTuvwXYZ
       TELEGRAM_CHAT_ID=123456789

Alert types fired by BDE:
  1. IAS window closing  — Tier 1-2 hypothesis appears in Tier 3-4 media
  2. New Tier-1 signal   — hypothesis crosses OPS ≥ 0.60 for the first time
  3. ACH review needed   — hypothesis confidence crosses 0.80
  4. Daily digest        — ranked active opportunities, sent at 08:00 UTC
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import requests
from loguru import logger

_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
_API_URL = f"https://api.telegram.org/bot{_TOKEN}/sendMessage"
_TIMEOUT = 10


def is_configured() -> bool:
    return bool(_TOKEN and _CHAT_ID)


def send(text: str) -> bool:
    """Send a Telegram HTML message. Returns True on success."""
    if not is_configured():
        logger.info(f"[Telegram not configured] {text[:80]}")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{_TOKEN}/sendMessage",
            json={
                "chat_id": _CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


# ─────────────────────────────────────────────
# Alert formatters
# ─────────────────────────────────────────────

def alert_ias_window_closing(
    hyp_id: str,
    statement: str,
    node_name: str,
    confidence: float,
    ops_score: float,
    awareness_layer: int,
    articles: list[dict],
) -> bool:
    sources = list(dict.fromkeys(a.get("source", "") for a in articles))
    article_lines = "\n".join(
        f"  • <b>{a.get('source', '')}</b>: {(a.get('title') or '')[:90]}"
        for a in articles[:3]
    )
    more = f"\n  …and {len(articles) - 3} more" if len(articles) > 3 else ""

    msg = (
        f"⚠️ <b>IAS WINDOW CLOSING — {node_name}</b>\n\n"
        f"<i>{statement[:160]}</i>\n\n"
        f"Now in Tier 3-4 media ({', '.join(sources[:3])}):\n"
        f"{article_lines}{more}\n\n"
        f"OPS: <b>{ops_score:.3f}</b>  ·  "
        f"Confidence: <b>{confidence:.0%}</b>  ·  "
        f"Layer: <b>{awareness_layer}</b> → <b>4</b>\n\n"
        f"<b>Act or re-evaluate — signal going mainstream.</b>"
    )
    return send(msg)


def alert_new_tier1(
    node_name: str,
    node_id: str,
    statement: str,
    srs_score: float,
    confidence: float,
    ops_score: float,
    awareness_layer: int,
    falsification_criteria: list[str],
) -> bool:
    layer_desc = {1: "internal/procurement", 2: "specialist", 3: "analyst", 4: "mainstream media"}
    fc_lines = "\n".join(
        f"  {i}. {c}" for i, c in enumerate(falsification_criteria[:3], 1)
    ) or "  (none set)"

    msg = (
        f"🔍 <b>NEW BOTTLENECK SIGNAL — {node_name}</b>\n\n"
        f"<i>{statement[:180]}</i>\n\n"
        f"SRS: <b>{srs_score:.3f}</b>  ·  "
        f"OPS: <b>{ops_score:.3f}</b>  ·  "
        f"Confidence: <b>{confidence:.0%}</b>\n"
        f"Awareness: Layer {awareness_layer} — {layer_desc.get(awareness_layer, str(awareness_layer))}\n\n"
        f"Falsification criteria:\n{fc_lines}\n\n"
        f"Monitor for Tier 3 analyst coverage as the IAS window opens."
    )
    return send(msg)


def alert_ach_needed(
    node_name: str,
    hyp_id: str,
    confidence: float,
    ops_score: float,
) -> bool:
    msg = (
        f"🔬 <b>ACH REVIEW NEEDED — {node_name}</b>\n\n"
        f"Hypothesis <code>{hyp_id[:12]}</code> reached "
        f"<b>{confidence:.0%}</b> confidence (OPS {ops_score:.3f}).\n\n"
        f"Open the dashboard → Hypothesis Detail → run ACH before promoting to Tier 1."
    )
    return send(msg)


def send_daily_digest(
    opportunities: list[dict],
    ingest_count: int = 0,
    new_this_week: int = 0,
) -> bool:
    date_str  = datetime.now(timezone.utc).strftime("%a %b %d")
    tier_icon = {1: "🔴", 2: "🟠", 3: "🟡"}

    if not opportunities:
        return send(
            f"📊 <b>BDE Daily Digest — {date_str}</b>\n\n"
            f"No active opportunities at this time.\n"
            f"Documents ingested: {ingest_count}"
        )

    lines = []
    for i, o in enumerate(opportunities[:6], 1):
        icon = tier_icon.get(o.get("tier", 3), "⚪")
        name = o.get("node_name") or o.get("node_id", "?")
        ops  = o.get("ops_final", 0)
        conf = o.get("confidence", 0)
        stmt = (o.get("statement") or "")[:70]
        lines.append(
            f"{i}. {icon} <b>{name}</b>  OPS {ops:.3f}  ·  {conf:.0%} conf\n"
            f"   <i>{stmt}</i>"
        )

    tier1 = sum(1 for o in opportunities if o.get("tier") == 1)
    tier2 = sum(1 for o in opportunities if o.get("tier") == 2)

    msg = (
        f"📊 <b>BDE Daily Digest — {date_str}</b>\n\n"
        f"Active: <b>{len(opportunities)}</b> opportunities "
        f"({tier1} Tier 1, {tier2} Tier 2)\n"
        f"New this week: <b>{new_this_week}</b>  ·  "
        f"Docs ingested: <b>{ingest_count}</b>\n\n"
        + "\n\n".join(lines)
    )
    return send(msg)
