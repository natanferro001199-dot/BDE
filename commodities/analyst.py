"""
analyst.py — Daily 5-agent commodity shortage intelligence via local Mistral 7B.

One structured Mistral call per commodity simulates all five analysts:
  1. Supply Analyst      — production, inventory, deficits
  2. Geopolitical Risk   — export controls, sanctions, resource nationalism
  3. Mining/Engineering  — mine timelines, refining constraints, lead times
  4. Demand Analyst      — AI infra, defense, energy transition demand
  5. Skeptic             — challenges every thesis, finds consensus errors

Supply Stress Score (0-100) = weighted composite of 9 sub-scores.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import date
from pathlib import Path

import httpx
from loguru import logger

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import OLLAMA_BASE_URL, ROUTING_MODEL, DATA_DIR

OLLAMA_GENERATE = f"{OLLAMA_BASE_URL}/api/generate"
TIMEOUT = 90  # seconds per commodity; Mistral 7B typical: 20-40s
INGEST_DB = Path(DATA_DIR) / "ingest_queue.db"
MAX_ARTICLES = 3

WEIGHTS: dict[str, float] = {
    "supply_growth_score":              0.15,
    "demand_growth_score":              0.15,
    "inventory_depletion_score":        0.15,
    "geographic_concentration_score":   0.15,
    "refining_concentration_score":     0.10,
    "geopolitical_risk_score":          0.10,
    "export_restriction_score":         0.10,
    "replacement_difficulty_score":     0.05,
    "production_lead_time_score":       0.05,
}

# ── Prompt template ────────────────────────────────────────────────────────────
# Engineering notes:
# - Example JSON uses real enum values ("bearish") not placeholders — prevents
#   Mistral copying angle-bracket syntax literally (known 7B failure mode)
# - "Output ONLY the raw JSON" + immediate { primes the model to continue in JSON
# - Agent roles described as output fields, not as a multi-turn conversation —
#   multi-turn debate instructions cause 7B models to hallucinate dialogue
# - 1-sentence constraint on agent findings prevents token blowup and truncation
# - num_predict=1500 in API call prevents early cutoff (default can be 128)

_PROMPT = """\
You are a commodity supply chain intelligence system.
Analyze this commodity for supply shortage risk.

COMMODITY: {name} ({sector}) — measured in {unit}
BACKGROUND: {description}
KEY PRODUCERS: {key_producers}

RECENT NEWS ({n_articles} articles from the last 7 days):
{article_context}

TASK: Produce a structured supply shortage assessment by simulating five expert analysts.

ANALYST ROLES:
1. Supply Analyst: assess current production volumes, inventory levels, known supply deficits, refinery utilization
2. Geopolitical Risk Analyst: assess export controls, sanctions, trade restrictions, resource nationalism, country concentration
3. Mining/Engineering Analyst: assess mine development lead times, refinery bottlenecks, capex cycles, technical substitution feasibility
4. Demand Analyst: assess demand from AI infrastructure, defense, energy transition, semiconductors, agriculture
5. Skeptic/Portfolio Manager: challenge the shortage thesis — where is consensus wrong, what could increase supply, what market already prices in

After the five-analyst debate, score each dimension 0 to 100 where 0 means no stress and 100 means maximum shortage stress.

Output ONLY the raw JSON object below. No markdown fences, no backticks, no explanatory text before or after.
{
  "supply_growth_score": 45,
  "demand_growth_score": 70,
  "inventory_depletion_score": 60,
  "geographic_concentration_score": 85,
  "refining_concentration_score": 80,
  "geopolitical_risk_score": 75,
  "export_restriction_score": 65,
  "replacement_difficulty_score": 90,
  "production_lead_time_score": 70,
  "outlook_6m": "bearish",
  "outlook_12m": "bearish",
  "outlook_3y": "neutral",
  "outlook_5y": "bullish",
  "confidence": 3,
  "consensus": "divided",
  "agent1_finding": "One sentence from Supply Analyst about current supply balance.",
  "agent2_finding": "One sentence from Geopolitical Risk Analyst about country or policy risk.",
  "agent3_finding": "One sentence from Mining Engineer about capacity expansion timeline.",
  "agent4_finding": "One sentence from Demand Analyst about consumption growth driver.",
  "agent5_critique": "One sentence from Skeptic challenging the shortage thesis.",
  "key_catalysts": ["First event that would worsen shortage", "Second catalyst", "Third catalyst"],
  "key_risks": ["First event that would resolve shortage", "Second risk to the thesis"],
  "monitoring_indicators": ["First metric to watch weekly", "Second indicator", "Third indicator"]
}

Replace the example numbers and text with your actual assessment for {name}.
outlook values must be exactly one of: bearish, neutral, bullish
consensus values must be exactly one of: tight, divided, contested
confidence must be an integer 1 (low) to 5 (high)
"""


# ── JSON extraction ────────────────────────────────────────────────────────────

def _extract_json(raw: str) -> dict | None:
    # Try markdown code fence first
    fence = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        candidate = raw[start: end + 1]

    # Try direct parse
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Try repairing truncated JSON by appending closing characters
    for suffix in ["}", "}}", "}\"}", "]}"]:
        try:
            return json.loads(candidate + suffix)
        except json.JSONDecodeError:
            continue
    return None


def _validate_score(val, default: int = 50) -> int:
    try:
        return max(0, min(100, int(float(str(val)))))
    except (TypeError, ValueError):
        return default


_VALID_OUTLOOKS = {"bearish", "neutral", "bullish"}
_OUTLOOK_ALIASES = {
    "very bearish": "bearish", "strongly bearish": "bearish", "negative": "bearish",
    "slightly bearish": "bearish", "mildly bearish": "bearish", "tight": "bearish",
    "very bullish": "bullish", "strongly bullish": "bullish", "positive": "bullish",
    "slightly bullish": "bullish", "mildly bullish": "bullish", "constructive": "bullish",
    "flat": "neutral", "stable": "neutral", "mixed": "neutral", "balanced": "neutral",
}


def _normalize_outlook(val) -> str:
    if not val:
        return "neutral"
    v = str(val).lower().strip().rstrip(".")
    if v in _VALID_OUTLOOKS:
        return v
    for alias, normalized in _OUTLOOK_ALIASES.items():
        if alias in v:
            return normalized
    if any(w in v for w in ("bear", "short", "deficit", "constrain", "shortage")):
        return "bearish"
    if any(w in v for w in ("bull", "surplus", "ease", "recover")):
        return "bullish"
    return "neutral"


def _normalize_consensus(val) -> str:
    if not val:
        return "divided"
    v = str(val).lower().strip()
    if "tight" in v or "unanim" in v or "strong" in v or "clear" in v:
        return "tight"
    if "contest" in v or "sharp" in v or "disagree" in v:
        return "contested"
    return "divided"


def _safe_list(val, max_items: int = 5) -> list[str]:
    if not isinstance(val, list):
        return []
    return [str(item)[:200] for item in val[:max_items]]


# ── Article context ────────────────────────────────────────────────────────────

def _get_article_context(commodity: dict) -> tuple[str, int]:
    if not INGEST_DB.exists():
        return "No news database available — using training knowledge only.", 0

    aliases = [commodity["name"]] + commodity.get("aliases", [])
    seen: set[str] = set()
    found: list[tuple] = []

    try:
        conn = sqlite3.connect(str(INGEST_DB))
        conn.execute("PRAGMA journal_mode=WAL")
        for term in aliases:
            if len(found) >= MAX_ARTICLES:
                break
            rows = conn.execute(
                """SELECT uid, title, text, published_at, source
                   FROM documents
                   WHERE (title LIKE ? OR text LIKE ?)
                     AND published_at >= datetime('now', '-7 days')
                   ORDER BY published_at DESC
                   LIMIT ?""",
                (f"%{term}%", f"%{term}%", MAX_ARTICLES),
            ).fetchall()
            for row in rows:
                if row[0] not in seen and len(found) < MAX_ARTICLES:
                    seen.add(row[0])
                    found.append(row)
        conn.close()
    except Exception as e:
        logger.warning(f"[analyst] Article query failed for {commodity['name']}: {e}")
        return f"News query failed — using training knowledge only.", 0

    if not found:
        return f"No recent news found for {commodity['name']} in the last 7 days — using training knowledge.", 0

    parts = []
    for _, title, text, pub_at, source in found:
        excerpt = (text or "")[:400].strip()
        pub_date = (pub_at or "")[:10]
        parts.append(f"[{pub_date} | {source}] {title}\n{excerpt}")
    return "\n\n---\n\n".join(parts), len(found)


# ── Score computation ──────────────────────────────────────────────────────────

def _compute_supply_stress(parsed: dict) -> float:
    return round(
        sum(
            _validate_score(parsed.get(field, 50)) * weight
            for field, weight in WEIGHTS.items()
        ),
        2,
    )


# ── Main per-commodity analysis ────────────────────────────────────────────────

def analyze_commodity(commodity: dict) -> dict:
    name = commodity["name"]
    article_context, n_articles = _get_article_context(commodity)

    prompt = _PROMPT.format(
        name=name,
        sector=commodity.get("sector", ""),
        unit=commodity.get("unit", ""),
        description=commodity.get("description", ""),
        key_producers=commodity.get("key_producers", ""),
        n_articles=n_articles,
        article_context=article_context,
    )

    try:
        resp = httpx.post(
            OLLAMA_GENERATE,
            json={
                "model": ROUTING_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 1500, "temperature": 0.2},
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")
    except Exception as e:
        logger.warning(f"[analyst] Ollama call failed for {name}: {e}")
        return {
            "commodity": name,
            "sector": commodity.get("sector"),
            "articles_used": n_articles,
            "parse_error": True,
            "supply_stress_score": None,
        }

    parsed = _extract_json(raw)
    if not parsed:
        logger.warning(f"[analyst] JSON parse failed for {name}. Raw: {raw[:200]}")
        return {
            "commodity": name,
            "sector": commodity.get("sector"),
            "articles_used": n_articles,
            "parse_error": True,
            "supply_stress_score": None,
        }

    supply_stress_score = _compute_supply_stress(parsed)

    return {
        "commodity": name,
        "sector": commodity.get("sector"),
        "supply_stress_score": supply_stress_score,
        # raw sub-scores
        "supply_growth_score":              _validate_score(parsed.get("supply_growth_score")),
        "demand_growth_score":              _validate_score(parsed.get("demand_growth_score")),
        "inventory_depletion_score":        _validate_score(parsed.get("inventory_depletion_score")),
        "geographic_concentration_score":   _validate_score(parsed.get("geographic_concentration_score")),
        "refining_concentration_score":     _validate_score(parsed.get("refining_concentration_score")),
        "geopolitical_risk_score":          _validate_score(parsed.get("geopolitical_risk_score")),
        "export_restriction_score":         _validate_score(parsed.get("export_restriction_score")),
        "replacement_difficulty_score":     _validate_score(parsed.get("replacement_difficulty_score")),
        "production_lead_time_score":       _validate_score(parsed.get("production_lead_time_score")),
        # qualitative
        "outlook_6m":   _normalize_outlook(parsed.get("outlook_6m")),
        "outlook_12m":  _normalize_outlook(parsed.get("outlook_12m")),
        "outlook_3y":   _normalize_outlook(parsed.get("outlook_3y")),
        "outlook_5y":   _normalize_outlook(parsed.get("outlook_5y")),
        "confidence":   max(1, min(5, int(parsed.get("confidence") or 3))),
        "consensus":    _normalize_consensus(parsed.get("consensus")),
        "agent1_finding":  str(parsed.get("agent1_finding") or "")[:500],
        "agent2_finding":  str(parsed.get("agent2_finding") or "")[:500],
        "agent3_finding":  str(parsed.get("agent3_finding") or "")[:500],
        "agent4_finding":  str(parsed.get("agent4_finding") or "")[:500],
        "agent5_critique": str(parsed.get("agent5_critique") or "")[:500],
        "key_catalysts":         _safe_list(parsed.get("key_catalysts")),
        "key_risks":             _safe_list(parsed.get("key_risks")),
        "monitoring_indicators": _safe_list(parsed.get("monitoring_indicators")),
        "articles_used": n_articles,
        "parse_error": False,
    }


# ── Batch runner ───────────────────────────────────────────────────────────────

def run_all() -> dict:
    from commodities.commodity_list import COMMODITIES
    from commodities.store import CommodityStore

    store = CommodityStore()
    run_date = date.today().isoformat()

    if store.get_latest_run_date() == run_date:
        logger.info(f"[analyst] Already ran for {run_date} — skipping")
        return {"status": "skipped", "date": run_date, "reason": "already_run_today"}

    results: list[dict] = []
    failed = 0
    t0 = time.monotonic()

    for i, commodity in enumerate(COMMODITIES, 1):
        name = commodity["name"]
        logger.info(f"[analyst] {i}/{len(COMMODITIES)}: {name}")
        result = analyze_commodity(commodity)
        if result.get("parse_error"):
            failed += 1
        results.append(result)

    elapsed = time.monotonic() - t0
    saved = store.save_ranking(run_date, results)
    succeeded = len(results) - failed

    logger.info(
        f"[analyst] Done: {succeeded}/{len(results)} succeeded, "
        f"{saved} saved, {elapsed:.0f}s"
    )
    return {
        "status": "complete",
        "date": run_date,
        "total": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "saved": saved,
        "elapsed_seconds": round(elapsed, 1),
    }
