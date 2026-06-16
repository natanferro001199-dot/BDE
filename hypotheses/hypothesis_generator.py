"""
hypothesis_generator.py — Generates falsifiable supply-chain bottleneck hypotheses
from high-SRS taxonomy nodes using Mistral 7B via Ollama.

For each top-SRS node that doesn't yet have an active hypothesis, generates:
  - A falsifiable statement about the bottleneck
  - 3 falsification criteria (conditions that would disprove the hypothesis)
  - Initial confidence (= normalized SRS score)
  - Awareness layer = 1 (internal, not yet in public discourse)

Runs weekly via Celery beat.
"""
from __future__ import annotations

import json
import re

import httpx
from loguru import logger

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import OLLAMA_BASE_URL, ROUTING_MODEL
from analysis.structural_analyzer import top_bottlenecks
from hypotheses.hypothesis_manager import HypothesisManager

OLLAMA_GENERATE = f"{OLLAMA_BASE_URL}/api/generate"
TIMEOUT = 120
MIN_SRS_FOR_HYPOTHESIS = 0.40
MAX_HYPOTHESES_PER_RUN = 10


PROMPT_TEMPLATE = """\
You are a supply chain risk analyst specialising in AI semiconductors.

A bottleneck discovery engine has identified this node as a critical supply chain risk:
  Node: {name} ({label})
  SRS Score: {srs_score} (0=no risk, 1=maximum risk)
  Betweenness centrality: {betweenness} (fraction of supply paths passing through this node)
  Supplier concentration: {concentration} (0=many suppliers, 1=sole source)
  Articulation point: {is_ap} (true = removing this node disconnects the supply graph)

Generate a single falsifiable hypothesis about this supply chain bottleneck.

Respond with ONLY this JSON (no markdown, no extra text):
{{
  "statement": "one clear falsifiable sentence about what makes this a bottleneck",
  "falsification_criteria": [
    "condition 1 that would disprove this hypothesis",
    "condition 2 that would disprove this hypothesis",
    "condition 3 that would disprove this hypothesis"
  ],
  "confidence": 0.0_to_1.0,
  "reasoning": "one sentence explaining the risk"
}}

Rules:
- statement must be falsifiable (specific, not vague)
- falsification_criteria must be concrete observable events
- confidence should reflect the SRS score ({srs_score})
"""


def _call_mistral(prompt: str) -> dict | None:
    try:
        resp = httpx.post(
            OLLAMA_GENERATE,
            json={"model": ROUTING_MODEL, "prompt": prompt, "stream": False},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")
    except Exception as e:
        logger.warning(f"Mistral call failed: {e}")
        return None

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def generate_for_node(node: dict, mgr: HypothesisManager) -> str | None:
    """Generate one hypothesis for a node. Returns hypothesis id or None."""
    existing = mgr.for_node(node["node_id"])
    if any(h["status"] == "active" for h in existing):
        logger.debug(f"Skipping {node['node_id']} — already has active hypothesis")
        return None

    prompt = PROMPT_TEMPLATE.format(
        name=node.get("name", ""),
        label=node.get("label", ""),
        srs_score=round(float(node.get("srs_score") or 0), 3),
        betweenness=round(float(node.get("betweenness") or 0), 3),
        concentration=round(float(node.get("concentration") or 0), 3),
        is_ap=str(bool(node.get("is_articulation_point"))),
    )

    result = _call_mistral(prompt)
    if not result:
        logger.warning(f"No hypothesis generated for {node['node_id']}")
        return None

    statement = str(result.get("statement", "")).strip()
    falsification = result.get("falsification_criteria", [])
    confidence = float(result.get("confidence", float(node.get("srs_score") or 0.5)))

    if not statement or len(falsification) < 2:
        logger.warning(f"Incomplete hypothesis for {node['node_id']}")
        return None

    hid = mgr.create(
        node_id=node["node_id"],
        node_name=node.get("name", ""),
        statement=statement,
        confidence=min(confidence, 0.85),
        awareness_layer=1,
        falsification_criteria=falsification[:3],
        srs_score=float(node.get("srs_score") or 0),
    )
    logger.info(f"Generated hypothesis {hid[:8]}... for {node['node_id']} ({node.get('name')})")
    logger.debug(f"  Statement: {statement[:100]}")
    return hid


def run(top_n: int = MAX_HYPOTHESES_PER_RUN) -> dict:
    mgr = HypothesisManager()
    candidates = top_bottlenecks(n=top_n * 2)
    candidates = [c for c in candidates if float(c.get("srs_score") or 0) >= MIN_SRS_FOR_HYPOTHESIS]

    generated = 0
    skipped = 0
    for node in candidates[:top_n]:
        hid = generate_for_node(node, mgr)
        if hid:
            generated += 1
        else:
            skipped += 1

    counts = mgr.counts()
    logger.info(f"Hypothesis generator done. Generated: {generated}, Skipped: {skipped}. {counts}")
    return {"generated": generated, "skipped": skipped, **counts}


if __name__ == "__main__":
    print(run(top_n=5))
