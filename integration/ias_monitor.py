"""
ias_monitor.py — Detects when a BDE hypothesis moves from Tier 1-2 awareness
into Tier 3-4 financial media coverage, signalling the IAS window is closing.

How it works:
  1. Register active BDE hypotheses with their keywords
  2. Every 6 hours (via Celery beat), check news-sentiment's article store
  3. If hypothesis keywords appear in recent Tier 3-4 articles, fire an alert

Persistence note:
  alerted_layers must be persisted between runs to avoid repeat alerts.
  Until BDE Phase 5 (Hypothesis Engine) is built, store alerted state in
  BDE's tracking DB (bde_tracking.db). When Neo4j is live, move it there.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger

NS_DB_PATH = Path(
    os.getenv(
        "NS_DB_PATH",
        Path(__file__).resolve().parents[2] / "data" / "news.db",
    )
)

BDE_TRACKING_DB = Path(
    os.getenv(
        "BDE_TRACKING_DB",
        Path(__file__).resolve().parents[1] / "data" / "bde_tracking.db",
    )
)


@dataclass
class WatchedHypothesis:
    id: str               # BDE hypothesis ID e.g. "BN-2024-047"
    statement: str        # the explicit claim
    keywords: list[str]   # key terms to watch for in financial media
    confidence: float     # current BDE confidence score (0-1)
    ops_score: float      # current OPS score
    awareness_layer: int  # current IAS layer estimate (0-5)
    alerted_layers: list[int] = field(default_factory=list)


def _word_boundary_match(keyword: str, text: str) -> bool:
    return bool(re.search(r"\b" + re.escape(keyword.lower()) + r"\b", text.lower()))


def _article_matches(article_title: str, hyp: WatchedHypothesis) -> bool:
    return any(_word_boundary_match(kw, article_title) for kw in hyp.keywords)


def load_alerted_layers(
    hypothesis_id: str,
    tracking_db_path: Path = BDE_TRACKING_DB,
) -> list[int]:
    """Load persisted alerted layers for a hypothesis from BDE's tracking DB."""
    tracking_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(tracking_db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ias_alerts (
            hypothesis_id TEXT,
            layer         INTEGER,
            alerted_at    TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (hypothesis_id, layer)
        )
        """
    )
    conn.commit()
    rows = conn.execute(
        "SELECT layer FROM ias_alerts WHERE hypothesis_id = ?", (hypothesis_id,)
    ).fetchall()
    conn.close()
    return [row[0] for row in rows]


def persist_alert(
    hypothesis_id: str,
    layer: int,
    tracking_db_path: Path = BDE_TRACKING_DB,
) -> None:
    """Record that we alerted for this hypothesis at this layer."""
    tracking_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(tracking_db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ias_alerts "
        "(hypothesis_id TEXT, layer INTEGER, alerted_at TEXT DEFAULT CURRENT_TIMESTAMP, "
        "PRIMARY KEY (hypothesis_id, layer))"
    )
    conn.execute(
        "INSERT OR IGNORE INTO ias_alerts (hypothesis_id, layer) VALUES (?, ?)",
        (hypothesis_id, layer),
    )
    conn.commit()
    conn.close()


def check_tier34_coverage(
    hypotheses: list[WatchedHypothesis],
    db_path: Path = NS_DB_PATH,
    lookback_hours: int = 24,
) -> list[tuple[WatchedHypothesis, list[dict]]]:
    """
    For each hypothesis, find recent Tier 3-4 articles that cover it.
    Returns (hypothesis, matching_articles) pairs only where matches exist.
    """
    if not hypotheses:
        return []

    if not db_path.exists():
        logger.warning(
            f"news-sentiment DB not found at {db_path} — skipping IAS layer check."
        )
        return []

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT uid, title, url, source, sentiment_score, first_seen
        FROM seen
        WHERE datetime(first_seen) >= datetime('now', ? )
        ORDER BY first_seen DESC
        """,
        (f"-{int(lookback_hours)} hours",),
    ).fetchall()
    conn.close()

    hits: list[tuple[WatchedHypothesis, list[dict]]] = []
    for hyp in hypotheses:
        matching = [
            {
                "uid": row["uid"],
                "title": row["title"],
                "url": row["url"],
                "source": row["source"],
                "sentiment_score": row["sentiment_score"],
                "first_seen": row["first_seen"],
            }
            for row in rows
            if _article_matches(row["title"] or "", hyp)
        ]
        if matching:
            hits.append((hyp, matching))

    return hits


def should_alert(hyp: WatchedHypothesis, articles: list[dict]) -> bool:
    """
    Return True if this is a new IAS layer progression worth alerting on.

    Does NOT alert if:
    - We already alerted at Tier 4 (in-session dedup via alerted_layers)
    - The hypothesis is already at Tier 4 or higher (no progression)
    """
    new_tier = 4
    if new_tier in hyp.alerted_layers:
        return False
    if hyp.awareness_layer >= new_tier:
        return False
    return True


def format_ias_alert(hyp: WatchedHypothesis, articles: list[dict]) -> str:
    """Format a Telegram-ready HTML alert for IAS window progression."""
    sources = list(dict.fromkeys(a["source"] for a in articles))  # ordered unique
    article_lines = "\n".join(
        f"  • <b>{a['source']}</b>: {a['title'][:90]}"
        for a in articles[:3]
    )
    more = f"\n  ...and {len(articles) - 3} more" if len(articles) > 3 else ""

    return (
        f"⚠️ <b>IAS WINDOW CLOSING — {hyp.id}</b>\n\n"
        f"<i>{hyp.statement[:150]}</i>\n\n"
        f"Now in Tier 3-4 financial media ({', '.join(sources[:3])}):\n"
        f"{article_lines}{more}\n\n"
        f"OPS: <b>{hyp.ops_score:.1f}</b>  |  "
        f"Confidence: <b>{hyp.confidence:.0%}</b>  |  "
        f"Layer: <b>{hyp.awareness_layer}</b> → <b>4</b>\n\n"
        f"<b>Act or re-evaluate before this is fully priced in.</b>"
    )


def run_check(
    hypotheses: list[WatchedHypothesis],
    send_alert_fn=None,
    db_path: Path = NS_DB_PATH,
    tracking_db_path: Path = BDE_TRACKING_DB,
    lookback_hours: int = 24,
) -> list[str]:
    """
    Run one IAS monitoring cycle. Returns list of hypothesis IDs that triggered alerts.
    Persists alert state so duplicate alerts don't fire on the next run.
    """
    # Load persisted alerted_layers for each hypothesis
    for hyp in hypotheses:
        persisted = load_alerted_layers(hyp.id, tracking_db_path)
        for layer in persisted:
            if layer not in hyp.alerted_layers:
                hyp.alerted_layers.append(layer)

    hits = check_tier34_coverage(hypotheses, db_path=db_path, lookback_hours=lookback_hours)
    alerted_ids = []

    for hyp, articles in hits:
        if not should_alert(hyp, articles):
            logger.debug(f"{hyp.id}: Tier 4 articles found but already alerted")
            continue

        msg = format_ias_alert(hyp, articles)
        logger.warning(
            f"IAS window closing for {hyp.id}: {len(articles)} articles in Tier 3-4"
        )

        if send_alert_fn:
            send_alert_fn(msg)

        hyp.alerted_layers.append(4)
        persist_alert(hyp.id, 4, tracking_db_path)
        alerted_ids.append(hyp.id)

    return alerted_ids
