"""
store.py — SQLite CRUD for daily commodity shortage rankings.

Database: data/commodity_rankings.db
One row per commodity per run_date.
Stores all 9 raw sub-scores plus the weighted composite Supply Stress Score.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from loguru import logger

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATA_DIR

COMMODITY_DB = Path(DATA_DIR) / "commodity_rankings.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS rankings (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date                        TEXT NOT NULL,
    commodity                       TEXT NOT NULL,
    sector                          TEXT,
    rank                            INTEGER,
    supply_stress_score             REAL,
    score_delta                     REAL DEFAULT 0.0,
    supply_growth_score             INTEGER,
    demand_growth_score             INTEGER,
    inventory_depletion_score       INTEGER,
    geographic_concentration_score  INTEGER,
    refining_concentration_score    INTEGER,
    geopolitical_risk_score         INTEGER,
    export_restriction_score        INTEGER,
    replacement_difficulty_score    INTEGER,
    production_lead_time_score      INTEGER,
    outlook_6m                      TEXT,
    outlook_12m                     TEXT,
    outlook_3y                      TEXT,
    outlook_5y                      TEXT,
    confidence                      INTEGER,
    consensus                       TEXT,
    agent1_finding                  TEXT,
    agent2_finding                  TEXT,
    agent3_finding                  TEXT,
    agent4_finding                  TEXT,
    agent5_critique                 TEXT,
    key_catalysts                   TEXT,
    key_risks                       TEXT,
    monitoring_indicators           TEXT,
    articles_used                   INTEGER DEFAULT 0,
    parse_error                     INTEGER DEFAULT 0,
    created_at                      TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_date, commodity)
)
"""


class CommodityStore:
    def __init__(self, db_path: Path = COMMODITY_DB) -> None:
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
            conn.execute(_CREATE_TABLE)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_date ON rankings(run_date)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_commodity ON rankings(commodity)"
            )

    # ── Reads ──────────────────────────────────────────────────────────────

    def get_latest_run_date(self) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(run_date) AS d FROM rankings"
            ).fetchone()
        return row["d"] if row and row["d"] else None

    def get_run_dates(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT run_date FROM rankings ORDER BY run_date DESC"
            ).fetchall()
        return [r["run_date"] for r in rows]

    def get_latest_ranking(self) -> list[dict]:
        latest = self.get_latest_run_date()
        if not latest:
            return []
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM rankings WHERE run_date = ?
                   ORDER BY CASE WHEN rank IS NULL THEN 9999 ELSE rank END ASC""",
                (latest,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_yesterday_scores(self) -> dict[str, float]:
        """Most recent run_date before today → {commodity: supply_stress_score}."""
        today = date.today().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(run_date) AS d FROM rankings WHERE run_date < ?",
                (today,),
            ).fetchone()
            if not row or not row["d"]:
                return {}
            rows = conn.execute(
                "SELECT commodity, supply_stress_score FROM rankings WHERE run_date = ?",
                (row["d"],),
            ).fetchall()
        return {r["commodity"]: float(r["supply_stress_score"] or 0) for r in rows}

    def get_commodity_history(self, commodity: str, days: int = 30) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT run_date, supply_stress_score, score_delta,
                          outlook_6m, outlook_12m, rank
                   FROM rankings
                   WHERE commodity = ?
                     AND run_date >= date('now', ?)
                   ORDER BY run_date ASC""",
                (commodity, f"-{days} days"),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Writes ─────────────────────────────────────────────────────────────

    def save_ranking(self, run_date: str, results: list[dict]) -> int:
        prev = self.get_yesterday_scores()

        # Sort: valid scores descending, parse errors at bottom
        valid = [r for r in results if not r.get("parse_error") and r.get("supply_stress_score") is not None]
        failed = [r for r in results if r.get("parse_error") or r.get("supply_stress_score") is None]
        valid.sort(key=lambda r: r["supply_stress_score"], reverse=True)

        saved = 0
        with self._conn() as conn:
            for rank, r in enumerate(valid, 1):
                score = float(r["supply_stress_score"])
                delta = round(score - prev.get(r["commodity"], score), 2)
                conn.execute(
                    """INSERT OR REPLACE INTO rankings
                       (run_date, commodity, sector, rank, supply_stress_score,
                        score_delta,
                        supply_growth_score, demand_growth_score,
                        inventory_depletion_score, geographic_concentration_score,
                        refining_concentration_score, geopolitical_risk_score,
                        export_restriction_score, replacement_difficulty_score,
                        production_lead_time_score,
                        outlook_6m, outlook_12m, outlook_3y, outlook_5y,
                        confidence, consensus,
                        agent1_finding, agent2_finding, agent3_finding,
                        agent4_finding, agent5_critique,
                        key_catalysts, key_risks, monitoring_indicators,
                        articles_used, parse_error, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run_date, r["commodity"], r.get("sector"), rank, score, delta,
                        r.get("supply_growth_score"), r.get("demand_growth_score"),
                        r.get("inventory_depletion_score"), r.get("geographic_concentration_score"),
                        r.get("refining_concentration_score"), r.get("geopolitical_risk_score"),
                        r.get("export_restriction_score"), r.get("replacement_difficulty_score"),
                        r.get("production_lead_time_score"),
                        r.get("outlook_6m"), r.get("outlook_12m"), r.get("outlook_3y"), r.get("outlook_5y"),
                        r.get("confidence"), r.get("consensus"),
                        r.get("agent1_finding"), r.get("agent2_finding"), r.get("agent3_finding"),
                        r.get("agent4_finding"), r.get("agent5_critique"),
                        json.dumps(r.get("key_catalysts") or []),
                        json.dumps(r.get("key_risks") or []),
                        json.dumps(r.get("monitoring_indicators") or []),
                        r.get("articles_used", 0), 0,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                saved += 1

            for r in failed:
                conn.execute(
                    """INSERT OR REPLACE INTO rankings
                       (run_date, commodity, sector, rank, supply_stress_score,
                        score_delta, articles_used, parse_error, created_at)
                       VALUES (?,?,?,NULL,NULL,0.0,?,1,?)""",
                    (
                        run_date, r["commodity"], r.get("sector"),
                        r.get("articles_used", 0),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

        logger.info(f"[CommodityStore] Saved {saved}/{len(results)} rows for {run_date}")
        return saved
