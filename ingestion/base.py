"""
base.py — Shared Document dataclass and SQLite deduplication store for all BDE ingestors.

All ingestors normalize their output to Document before storing.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATA_DIR

INGEST_DB = Path(DATA_DIR) / "ingest_queue.db"


@dataclass
class Document:
    uid: str          # globally unique: f"{source}:{source_id}"
    title: str
    text: str         # full content or best available excerpt
    url: str
    source: str       # "github", "hn", "edgar", "arxiv", "rss_<name>"
    ias_tier: int     # 1 or 2
    published_at: str # ISO 8601 UTC
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.uid:
            self.uid = hashlib.sha256(self.url.encode()).hexdigest()[:16]
        if not self.published_at:
            self.published_at = datetime.now(timezone.utc).isoformat()


class IngestStore:
    """SQLite-backed dedup and queue store. Thread-safe via WAL mode."""

    def __init__(self, db_path: Path = INGEST_DB) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = str(db_path)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    uid          TEXT PRIMARY KEY,
                    source       TEXT NOT NULL,
                    title        TEXT,
                    url          TEXT,
                    ias_tier     INTEGER,
                    published_at TEXT,
                    text         TEXT,
                    metadata     TEXT,
                    ingested_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                    status       TEXT DEFAULT 'pending'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON documents(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON documents(source)")

    def is_known(self, uid: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM documents WHERE uid=?", (uid,)).fetchone()
        return row is not None

    def save(self, doc: Document) -> bool:
        """Insert doc; returns True if new, False if duplicate."""
        if self.is_known(doc.uid):
            return False
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO documents
                   (uid, source, title, url, ias_tier, published_at, text, metadata)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (doc.uid, doc.source, doc.title[:512], doc.url,
                 doc.ias_tier, doc.published_at,
                 doc.text[:8000], json.dumps(doc.metadata)),
            )
        return True

    def save_many(self, docs: list[Document]) -> int:
        new = [d for d in docs if not self.is_known(d.uid)]
        if not new:
            return 0
        with self._conn() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO documents
                   (uid, source, title, url, ias_tier, published_at, text, metadata)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [(d.uid, d.source, d.title[:512], d.url,
                  d.ias_tier, d.published_at, d.text[:8000],
                  json.dumps(d.metadata)) for d in new],
            )
        return len(new)

    def pending(self, limit: int = 100) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM documents WHERE status='pending' ORDER BY ingested_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
            cols = [d[0] for d in conn.execute("SELECT * FROM documents LIMIT 0").description or []]
        if not rows:
            return []
        cols = ["uid","source","title","url","ias_tier","published_at","text","metadata","ingested_at","status"]
        return [dict(zip(cols, r)) for r in rows]

    def mark_processed(self, uids: list[str]) -> None:
        with self._conn() as conn:
            conn.executemany(
                "UPDATE documents SET status='processed' WHERE uid=?",
                [(uid,) for uid in uids],
            )

    def counts(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM documents WHERE status='pending'").fetchone()[0]
            by_source = {
                r[0]: r[1]
                for r in conn.execute(
                    "SELECT source, COUNT(*) FROM documents GROUP BY source ORDER BY 2 DESC"
                ).fetchall()
            }
        return {"total": total, "pending": pending, "by_source": by_source}
