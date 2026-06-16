"""
hypothesis_manager.py — SQLite CRUD for BDE hypotheses.

Schema:
  id, node_id, statement, confidence, status, awareness_layer,
  evidence_for (JSON list), evidence_against (JSON list),
  falsification_criteria (JSON list), srs_score_at_creation,
  created_at, updated_at, ach_reviewed (bool)

Statuses: active, confirmed, falsified, stale
Awareness layers: 1 (internal), 2 (technical), 3 (media), 4 (mainstream)
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATA_DIR

HYPOTHESIS_DB = Path(DATA_DIR) / "hypotheses.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class HypothesisManager:
    def __init__(self, db_path: Path = HYPOTHESIS_DB) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = str(db_path)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hypotheses (
                    id                       TEXT PRIMARY KEY,
                    node_id                  TEXT NOT NULL,
                    node_name                TEXT,
                    statement                TEXT NOT NULL,
                    confidence               REAL DEFAULT 0.5,
                    status                   TEXT DEFAULT 'active',
                    awareness_layer          INTEGER DEFAULT 1,
                    evidence_for             TEXT DEFAULT '[]',
                    evidence_against         TEXT DEFAULT '[]',
                    falsification_criteria   TEXT DEFAULT '[]',
                    srs_score_at_creation    REAL,
                    ach_reviewed             INTEGER DEFAULT 0,
                    created_at               TEXT,
                    updated_at               TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hyp_status ON hypotheses(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hyp_node ON hypotheses(node_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hyp_conf ON hypotheses(confidence)")

    def create(
        self,
        node_id: str,
        node_name: str,
        statement: str,
        confidence: float = 0.50,
        awareness_layer: int = 1,
        falsification_criteria: list[str] | None = None,
        srs_score: float | None = None,
    ) -> str:
        hid = str(uuid.uuid4())
        now = _now()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO hypotheses
                   (id, node_id, node_name, statement, confidence, status,
                    awareness_layer, falsification_criteria, srs_score_at_creation,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (hid, node_id, node_name, statement, confidence, "active",
                 awareness_layer, json.dumps(falsification_criteria or []),
                 srs_score, now, now),
            )
        return hid

    def add_evidence(self, hid: str, evidence: str, supports: bool) -> None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT evidence_for, evidence_against, confidence FROM hypotheses WHERE id=?",
                (hid,),
            ).fetchone()
            if not row:
                return
            for_list = json.loads(row["evidence_for"])
            against_list = json.loads(row["evidence_against"])
            if supports:
                for_list.append(evidence)
                new_conf = min(row["confidence"] + 0.05, 0.95)
            else:
                against_list.append(evidence)
                new_conf = max(row["confidence"] - 0.08, 0.05)
            conn.execute(
                """UPDATE hypotheses
                   SET evidence_for=?, evidence_against=?, confidence=?, updated_at=?
                   WHERE id=?""",
                (json.dumps(for_list), json.dumps(against_list), new_conf, _now(), hid),
            )

    def set_status(self, hid: str, status: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE hypotheses SET status=?, updated_at=? WHERE id=?",
                (status, _now(), hid),
            )

    def mark_ach_reviewed(self, hid: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE hypotheses SET ach_reviewed=1, updated_at=? WHERE id=?",
                (_now(), hid),
            )

    def get(self, hid: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM hypotheses WHERE id=?", (hid,)).fetchone()
        return dict(row) if row else None

    def active(self, min_confidence: float = 0.0) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM hypotheses
                   WHERE status='active' AND confidence >= ?
                   ORDER BY confidence DESC""",
                (min_confidence,),
            ).fetchall()
        return [dict(r) for r in rows]

    def for_node(self, node_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM hypotheses WHERE node_id=? ORDER BY confidence DESC",
                (node_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM hypotheses").fetchone()[0]
            by_status = {
                r[0]: r[1]
                for r in conn.execute(
                    "SELECT status, COUNT(*) FROM hypotheses GROUP BY status"
                ).fetchall()
            }
            needs_ach = conn.execute(
                "SELECT COUNT(*) FROM hypotheses WHERE confidence>=0.80 AND ach_reviewed=0 AND status='active'"
            ).fetchone()[0]
        return {"total": total, "by_status": by_status, "needs_ach_review": needs_ach}

    def list_all(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM hypotheses ORDER BY confidence DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
