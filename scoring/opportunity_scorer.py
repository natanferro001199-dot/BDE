"""
opportunity_scorer.py — Phase 7: Computes the Opportunity Score (OPS) for each
active hypothesis and ranks them for the dashboard.

OPS formula:
  OPS = (DR × IAS × 0.40) + (S × 0.20) + (CM × 0.15) + (VA × 0.15) + (RT × 0.10)
  OPS_final = OPS × Robustness_ACH

Components:
  DR  = Disruption Risk = SRS score (Phase 4)
  IAS = Information Asymmetry Score = 1 - (awareness_layer / 4)
        Layer 1 → IAS 0.75, Layer 2 → IAS 0.50, Layer 3 → IAS 0.25, Layer 4 → IAS 0.0
  S   = Specificity = len(falsification_criteria) / 3 (max 1.0)
  CM  = Confidence Momentum = confidence (current)
  VA  = Validation = evidence_for / (evidence_for + evidence_against + 1)
  RT  = Recency = 1.0 if updated < 7 days ago, 0.5 if < 30 days, 0.1 otherwise
  Robustness_ACH = from ach_reviews table (default 1.0 if not yet reviewed)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from loguru import logger

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contrarian.ach_engine import get_ach_review
from hypotheses.hypothesis_manager import HypothesisManager


def _ias(awareness_layer: int) -> float:
    mapping = {1: 0.75, 2: 0.50, 3: 0.25, 4: 0.0}
    return mapping.get(awareness_layer, 0.25)


def _recency(updated_at: str) -> float:
    try:
        updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - updated).days
        if days < 7:
            return 1.0
        elif days < 30:
            return 0.5
        return 0.1
    except Exception:
        return 0.5


def score_hypothesis(h: dict) -> dict:
    srs = float(h.get("srs_score_at_creation") or 0.5)
    awareness = int(h.get("awareness_layer") or 1)
    confidence = float(h.get("confidence") or 0.5)

    fc = json.loads(h.get("falsification_criteria") or "[]")
    specificity = min(len(fc) / 3.0, 1.0)

    ef = json.loads(h.get("evidence_for") or "[]")
    ea = json.loads(h.get("evidence_against") or "[]")
    validation = len(ef) / max(1, len(ef) + len(ea))

    recency = _recency(h.get("updated_at") or h.get("created_at") or "")

    ias = _ias(awareness)
    ops_raw = (srs * ias * 0.40) + (specificity * 0.20) + (confidence * 0.15) + (validation * 0.15) + (recency * 0.10)

    ach = get_ach_review(h["id"])
    robustness = float(ach["robustness"]) if ach else 1.0
    ops_final = ops_raw * robustness

    tier = 1 if ops_final >= 0.60 else (2 if ops_final >= 0.35 else 3)

    return {
        "id": h["id"],
        "node_id": h.get("node_id"),
        "node_name": h.get("node_name"),
        "statement": h.get("statement"),
        "confidence": round(confidence, 3),
        "awareness_layer": awareness,
        "srs_score": round(srs, 3),
        "ias": round(ias, 3),
        "specificity": round(specificity, 3),
        "validation": round(validation, 3),
        "recency": round(recency, 3),
        "robustness_ach": round(robustness, 3),
        "ops_raw": round(ops_raw, 4),
        "ops_final": round(ops_final, 4),
        "tier": tier,
        "ach_reviewed": bool(h.get("ach_reviewed")),
        "evidence_for_count": len(ef),
        "evidence_against_count": len(ea),
        "falsification_criteria": fc,
        "status": h.get("status"),
        "created_at": h.get("created_at"),
        "updated_at": h.get("updated_at"),
    }


def ranked_opportunities(min_tier: int = 3) -> list[dict]:
    """Return all active hypotheses ranked by OPS_final, up to given tier."""
    mgr = HypothesisManager()
    active = mgr.active()
    scored = [score_hypothesis(h) for h in active]
    scored = [s for s in scored if s["tier"] <= min_tier]
    scored.sort(key=lambda x: x["ops_final"], reverse=True)
    return scored


def summary() -> dict:
    opps = ranked_opportunities()
    if not opps:
        return {"total": 0, "tier1": 0, "tier2": 0, "tier3": 0}
    return {
        "total": len(opps),
        "tier1": sum(1 for o in opps if o["tier"] == 1),
        "tier2": sum(1 for o in opps if o["tier"] == 2),
        "tier3": sum(1 for o in opps if o["tier"] == 3),
        "top_opportunity": opps[0] if opps else None,
    }


if __name__ == "__main__":
    opps = ranked_opportunities()
    if not opps:
        print("No active hypotheses yet.")
    else:
        print(f"\n{'Tier':<5} {'OPS':>6} {'Conf':>5} {'IAS':>5} {'Node':<20} Statement")
        print("-" * 90)
        for o in opps[:15]:
            print(f"T{o['tier']:<4} {o['ops_final']:>6.3f} {o['confidence']:>5.2f} "
                  f"{o['ias']:>5.2f} {(o['node_name'] or '')[:18]:<20} {(o['statement'] or '')[:50]}")
