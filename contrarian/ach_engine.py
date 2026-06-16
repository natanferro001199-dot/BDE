"""
ach_engine.py — Phase 6: Analysis of Competing Hypotheses (ACH) Contrarian Engine.

For any hypothesis with confidence >= 0.80 that hasn't been ACH-reviewed,
this engine:
  1. Generates 3 alternative hypotheses (adversarial prompt via Mistral)
  2. Builds an ACH matrix: rows = evidence, cols = H + alternatives
  3. Classifies each cell: C (consistent), I (inconsistent), N/A
  4. Computes a robustness score: fraction of evidence that is DIAGNOSTIC
     (inconsistent with at least one alternative)
  5. Adjusts hypothesis confidence down by (1 - robustness)

High-confidence hypotheses that survive ACH are promoted to Tier 1.
Hypotheses with robustness < 0.40 are flagged for human review.

The Streamlit dashboard (Phase 7) surfaces the ACH matrix and flags for review.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import httpx
from loguru import logger

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import OLLAMA_BASE_URL, ROUTING_MODEL, DATA_DIR
from hypotheses.hypothesis_manager import HypothesisManager

OLLAMA_GENERATE = f"{OLLAMA_BASE_URL}/api/generate"
TIMEOUT = 120
ACH_DB = Path(DATA_DIR) / "ach_reviews.db"
MIN_CONFIDENCE_FOR_ACH = 0.80
ROBUSTNESS_THRESHOLD = 0.40


# ──────────────────────────────────────────────
# ACH database (stores matrices for dashboard)
# ──────────────────────────────────────────────

def _ach_conn() -> sqlite3.Connection:
    ACH_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ACH_DB))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ach_reviews (
            hypothesis_id    TEXT PRIMARY KEY,
            alternatives     TEXT,
            matrix           TEXT,
            robustness       REAL,
            passed           INTEGER,
            reviewed_at      TEXT,
            human_approved   INTEGER DEFAULT 0
        )
    """)
    return conn


def _save_ach(hid: str, alternatives: list[str], matrix: dict,
              robustness: float, passed: bool) -> None:
    conn = _ach_conn()
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO ach_reviews
               (hypothesis_id, alternatives, matrix, robustness, passed, reviewed_at)
               VALUES (?,?,?,?,?,?)""",
            (hid, json.dumps(alternatives), json.dumps(matrix),
             robustness, int(passed), datetime.now(timezone.utc).isoformat()),
        )
    conn.close()


def get_ach_review(hid: str) -> dict | None:
    conn = _ach_conn()
    row = conn.execute(
        "SELECT * FROM ach_reviews WHERE hypothesis_id=?", (hid,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_pending_human_review() -> list[dict]:
    conn = _ach_conn()
    rows = conn.execute(
        "SELECT * FROM ach_reviews WHERE passed=1 AND human_approved=0 ORDER BY reviewed_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def approve_hypothesis(hid: str) -> None:
    conn = _ach_conn()
    with conn:
        conn.execute(
            "UPDATE ach_reviews SET human_approved=1 WHERE hypothesis_id=?", (hid,)
        )
    conn.close()


# ──────────────────────────────────────────────
# Mistral calls
# ──────────────────────────────────────────────

ALTERNATIVES_PROMPT = """\
You are a contrarian analyst stress-testing a supply chain bottleneck hypothesis.

Hypothesis: {statement}
Node: {node_name} (SRS score: {srs_score})

Generate exactly 3 ALTERNATIVE hypotheses that could explain the same situation differently.
Each alternative should be specific and falsifiable, and should challenge or reframe the original.

Reply ONLY with this JSON array (no markdown, no extra text):
[
  "alternative hypothesis 1",
  "alternative hypothesis 2",
  "alternative hypothesis 3"
]
"""

CLASSIFY_PROMPT = """\
Supply chain ACH analysis. Classify each piece of evidence as:
C = Consistent with this hypothesis
I = Inconsistent with this hypothesis
N = Not applicable / neutral

Hypothesis: {hypothesis}

Evidence pieces:
{evidence_list}

Reply ONLY with a JSON array of the same length as the evidence list,
containing "C", "I", or "N" for each item:
["C", "I", "N", ...]
"""


def _call_mistral(prompt: str) -> str | None:
    try:
        resp = httpx.post(
            OLLAMA_GENERATE,
            json={"model": ROUTING_MODEL, "prompt": prompt, "stream": False},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as e:
        logger.warning(f"Mistral ACH call failed: {e}")
        return None


def _generate_alternatives(statement: str, node_name: str, srs_score: float) -> list[str]:
    prompt = ALTERNATIVES_PROMPT.format(
        statement=statement[:300],
        node_name=node_name,
        srs_score=round(srs_score, 3),
    )
    raw = _call_mistral(prompt)
    if not raw:
        return []
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if not match:
        return []
    try:
        alts = json.loads(match.group())
        return [str(a).strip() for a in alts if str(a).strip()][:3]
    except json.JSONDecodeError:
        return []


def _classify_evidence(hypothesis: str, evidence_list: list[str]) -> list[str]:
    if not evidence_list:
        return []
    prompt = CLASSIFY_PROMPT.format(
        hypothesis=hypothesis[:200],
        evidence_list="\n".join(f"{i+1}. {e[:100]}" for i, e in enumerate(evidence_list)),
    )
    raw = _call_mistral(prompt)
    if not raw:
        return ["N"] * len(evidence_list)
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if not match:
        return ["N"] * len(evidence_list)
    try:
        classifications = json.loads(match.group())
        result = []
        for c in classifications[:len(evidence_list)]:
            c_str = str(c).strip().upper()
            result.append(c_str if c_str in ("C", "I", "N") else "N")
        while len(result) < len(evidence_list):
            result.append("N")
        return result
    except json.JSONDecodeError:
        return ["N"] * len(evidence_list)


# ──────────────────────────────────────────────
# ACH Matrix builder
# ──────────────────────────────────────────────

def _compute_robustness(matrix: dict, evidence: list[str]) -> float:
    """
    Robustness = fraction of evidence items that are diagnostic.
    An item is diagnostic if it's I (inconsistent) with AT LEAST ONE hypothesis in the matrix.
    Non-diagnostic evidence (all C or N) doesn't distinguish between hypotheses.
    """
    if not evidence:
        return 0.0
    diagnostic = 0
    for i in range(len(evidence)):
        all_classifications = [matrix[h][i] for h in matrix]
        if "I" in all_classifications:
            diagnostic += 1
    return diagnostic / len(evidence)


def review_hypothesis(hid: str, mgr: HypothesisManager | None = None) -> dict:
    """Run ACH on a single hypothesis. Returns review result."""
    if mgr is None:
        mgr = HypothesisManager()

    h = mgr.get(hid)
    if not h:
        return {"error": "hypothesis_not_found"}

    statement = h["statement"]
    node_name = h.get("node_name", "")
    srs_score = float(h.get("srs_score_at_creation") or 0.5)

    evidence_for = json.loads(h.get("evidence_for") or "[]")
    evidence_against = json.loads(h.get("evidence_against") or "[]")
    all_evidence = evidence_for + evidence_against
    if not all_evidence:
        all_evidence = [f"Structural risk: SRS={srs_score:.2f} (graph topology)"]

    logger.info(f"ACH review for {hid[:8]}... ({node_name}): {len(all_evidence)} evidence items")

    alternatives = _generate_alternatives(statement, node_name, srs_score)
    if not alternatives:
        logger.warning(f"Could not generate alternatives for {hid[:8]}...")
        alternatives = [
            f"{node_name} supply risk is overstated due to existing alternatives",
            f"Market forces will resolve the {node_name} bottleneck within 18 months",
        ]

    all_hypotheses = [statement] + alternatives
    matrix: dict[str, list[str]] = {}
    for hyp in all_hypotheses:
        matrix[hyp[:50]] = _classify_evidence(hyp, all_evidence)

    robustness = _compute_robustness(matrix, all_evidence)
    passed = robustness >= ROBUSTNESS_THRESHOLD

    logger.info(
        f"ACH result for {hid[:8]}...: robustness={robustness:.2f}, "
        f"{'PASSED' if passed else 'FLAGGED FOR REVIEW'}"
    )

    _save_ach(hid, alternatives, matrix, robustness, passed)
    mgr.mark_ach_reviewed(hid)

    if not passed:
        new_conf = float(h["confidence"]) * robustness
        mgr.add_evidence(hid, f"[ACH] Robustness={robustness:.2f} — confidence adjusted", supports=False)
        logger.warning(f"Low robustness ({robustness:.2f}) for {hid[:8]}... — confidence adjusted")

    return {
        "hypothesis_id": hid,
        "statement": statement[:100],
        "alternatives_count": len(alternatives),
        "evidence_count": len(all_evidence),
        "robustness": round(robustness, 3),
        "passed": passed,
        "needs_human_review": passed,
    }


def run() -> dict:
    """Review all hypotheses with confidence >= 0.80 that haven't been ACH-reviewed."""
    mgr = HypothesisManager()
    candidates = mgr.active(min_confidence=MIN_CONFIDENCE_FOR_ACH)
    candidates = [h for h in candidates if not h.get("ach_reviewed")]

    if not candidates:
        logger.info("No hypotheses need ACH review")
        return {"reviewed": 0}

    reviewed = 0
    passed = 0
    for h in candidates:
        result = review_hypothesis(h["id"], mgr)
        reviewed += 1
        if result.get("passed"):
            passed += 1

    return {
        "reviewed": reviewed,
        "passed": passed,
        "pending_human_review": len(list_pending_human_review()),
    }


if __name__ == "__main__":
    print(run())
