"""
orphan_queue.py — SQLite store for documents that couldn't be routed to any taxonomy node.

Phase 3 (EntityResolver) writes here when best similarity < 0.55.
Phase 7 (Dashboard) will surface these for manual review and taxonomy expansion.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATA_DIR

ORPHAN_DB = Path(DATA_DIR) / "orphan_queue.db"


class OrphanQueue:
    def __init__(self, db_path: Path = ORPHAN_DB) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = str(db_path)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS orphans (
                    uid              TEXT PRIMARY KEY,
                    doc_uid          TEXT NOT NULL,
                    title            TEXT,
                    text_excerpt     TEXT,
                    embedding        TEXT,
                    candidate_entities TEXT,
                    best_match_node  TEXT,
                    best_similarity  REAL,
                    reason           TEXT,
                    created_at       TEXT DEFAULT CURRENT_TIMESTAMP,
                    status           TEXT DEFAULT 'pending'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orphan_status ON orphans(status)")

    def add(
        self,
        doc_uid: str,
        title: str,
        text_excerpt: str,
        embedding: list[float],
        candidate_entities: list[str],
        best_match_node: str | None,
        best_similarity: float,
        reason: str,
    ) -> bool:
        uid = f"orphan:{doc_uid}"
        with self._conn() as conn:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO orphans
                       (uid, doc_uid, title, text_excerpt, embedding,
                        candidate_entities, best_match_node, best_similarity, reason)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (uid, doc_uid, title[:512], text_excerpt[:2000],
                     json.dumps(embedding), json.dumps(candidate_entities),
                     best_match_node, best_similarity, reason),
                )
                return conn.execute("SELECT changes()").fetchone()[0] > 0
            except Exception:
                return False

    def pending(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT uid, doc_uid, title, text_excerpt, candidate_entities,
                          best_match_node, best_similarity, reason, created_at
                   FROM orphans WHERE status='pending'
                   ORDER BY created_at ASC LIMIT ?""",
                (limit,),
            ).fetchall()
        cols = ["uid", "doc_uid", "title", "text_excerpt", "candidate_entities",
                "best_match_node", "best_similarity", "reason", "created_at"]
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            d["candidate_entities"] = json.loads(d["candidate_entities"] or "[]")
            result.append(d)
        return result

    def resolve(self, uid: str, node_id: str) -> None:
        """Mark an orphan as manually resolved."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE orphans SET status='resolved', best_match_node=? WHERE uid=?",
                (node_id, uid),
            )

    def dismiss(self, uid: str) -> None:
        """Mark as dismissed (genuinely out-of-scope)."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE orphans SET status='dismissed' WHERE uid=?",
                (uid,),
            )

    def counts(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM orphans").fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM orphans WHERE status='pending'"
            ).fetchone()[0]
            resolved = conn.execute(
                "SELECT COUNT(*) FROM orphans WHERE status='resolved'"
            ).fetchone()[0]
        return {"total": total, "pending": pending, "resolved": resolved}
