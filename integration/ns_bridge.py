"""
ns_bridge.py — Reads articles from news-sentiment's SQLite store and feeds
them into BDE's entity resolution pipeline as Tier 3-4 source documents.

news-sentiment covers Reuters, AP, Bloomberg, WSJ via RSS — the Tier 3-4
layer in BDE's IAS model. When these sources start covering a supply chain
topic, the IAS window is closing.

Design decisions:
- BDE tracking state (bde_ingested) lives in BDE's own DB, not news-sentiment's.
  This avoids write contention between the two processes on the same file.
- Both connections open in WAL mode so concurrent reads don't block writes.
- topics column is parsed defensively: handles NULL, empty string, and valid JSON.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Iterator

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

IAS_TIER = 4  # financial media layer in BDE's 6-layer IAS model

_EXPECTED_COLUMNS = {"uid", "title", "url", "source", "sentiment_score", "first_seen"}


def _connect_ns(db_path: Path) -> sqlite3.Connection:
    """Open news-sentiment DB read-only.
    WAL mode is set by news-sentiment's own Store; can't be set from a ro connection.
    """
    if not db_path.exists():
        raise FileNotFoundError(
            f"news-sentiment DB not found at {db_path}\n"
            "Make sure the news-sentiment pipeline has run at least once.\n"
            "Set NS_DB_PATH env var if the DB is at a different location."
        )
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    _validate_schema(conn)
    return conn


def _connect_tracking(db_path: Path) -> sqlite3.Connection:
    """Open BDE's own tracking DB (read-write) with WAL mode."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bde_ingested (
            uid         TEXT PRIMARY KEY,
            ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def _validate_schema(conn: sqlite3.Connection) -> None:
    """Fail fast if news-sentiment DB is missing expected columns."""
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(seen)")}
    except sqlite3.Error as e:
        raise RuntimeError(f"Could not read news-sentiment schema: {e}") from e
    missing = _EXPECTED_COLUMNS - cols
    if missing:
        raise RuntimeError(
            f"news-sentiment 'seen' table is missing expected columns: {missing}\n"
            "The schema may have changed — check for news-sentiment updates."
        )


def _parse_topics(raw: str | None) -> list[str]:
    """Parse topics field safely regardless of format (NULL, '', or JSON)."""
    if not raw or not raw.strip():
        return []
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, ValueError):
        # Fallback: treat as legacy comma-separated string
        return [t.strip() for t in raw.split(",") if t.strip()]


def fetch_new_articles(
    ns_db_path: Path = NS_DB_PATH,
    tracking_db_path: Path = BDE_TRACKING_DB,
) -> Iterator[dict]:
    """
    Yield articles from news-sentiment not yet processed by BDE.
    Each dict is ready to feed into BDE's entity resolution layer.
    """
    ns_conn = _connect_ns(ns_db_path)
    tracking_conn = _connect_tracking(tracking_db_path)

    try:
        rows = ns_conn.execute(
            """
            SELECT uid, title, url, source,
                   sentiment_score, sentiment_label, topics, first_seen
            FROM seen
            ORDER BY first_seen ASC
            """,
        ).fetchall()
    finally:
        ns_conn.close()

    # Check ingested in tracking DB since we can't JOIN across two DB files
    ingested_uids = {
        row[0]
        for row in tracking_conn.execute("SELECT uid FROM bde_ingested").fetchall()
    }
    tracking_conn.close()

    for row in rows:
        if row["uid"] in ingested_uids:
            continue
        yield {
            "uid": row["uid"],
            "title": row["title"],
            "url": row["url"],
            "source": row["source"],
            # news-sentiment stores only the title in the 'title' column;
            # the full text (title + summary) is not persisted to the DB.
            "text": row["title"] or "",
            "sentiment_score": row["sentiment_score"],
            "sentiment_label": row["sentiment_label"],
            "topics": _parse_topics(row["topics"]),
            "first_seen": row["first_seen"],
            "ias_tier": IAS_TIER,
        }


def mark_ingested(
    uids: list[str],
    tracking_db_path: Path = BDE_TRACKING_DB,
) -> None:
    """
    Mark articles as processed by BDE so they aren't re-ingested next cycle.
    Call after entity resolution has handled each article.
    """
    if not uids:
        return
    conn = _connect_tracking(tracking_db_path)
    conn.executemany(
        "INSERT OR IGNORE INTO bde_ingested (uid) VALUES (?)",
        [(uid,) for uid in uids],
    )
    conn.commit()
    conn.close()


def article_count(
    ns_db_path: Path = NS_DB_PATH,
    tracking_db_path: Path = BDE_TRACKING_DB,
) -> dict:
    """Return counts of total and unprocessed articles — useful for monitoring."""
    if not ns_db_path.exists():
        return {"total": 0, "pending_bde": 0}

    ns_conn = _connect_ns(ns_db_path)
    total = ns_conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
    ns_conn.close()

    tracking_conn = _connect_tracking(tracking_db_path)
    ingested = tracking_conn.execute("SELECT COUNT(*) FROM bde_ingested").fetchone()[0]
    tracking_conn.close()

    return {"total": total, "pending_bde": max(0, total - ingested)}
