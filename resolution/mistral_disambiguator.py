"""
mistral_disambiguator.py — Uses Mistral 7B to disambiguate entity mentions when
vector similarity is in the uncertain zone (0.55–0.80).

Takes the document excerpt and 2-5 candidate taxonomy nodes ranked by similarity.
Returns the best node_id, confidence, and reasoning, or None if undecided.
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

OLLAMA_GENERATE = f"{OLLAMA_BASE_URL}/api/generate"
TIMEOUT = 120


PROMPT_TEMPLATE = """\
Task: semiconductor supply chain entity disambiguation.

Document title: {title}
Excerpt (first 400 chars): {excerpt}

Top candidate taxonomy nodes (by embedding similarity):
{candidates_text}

Which node does this document PRIMARILY discuss?

Reply with ONLY this JSON (no markdown, no extra text):
{{"node_id": "EXACT_ID_FROM_LIST_OR_null", "confidence": 0.0_to_1.0, "reason": "one sentence"}}

IMPORTANT: node_id must be the exact string from the id= field above (e.g. COMP-001, MAT-015, GEO-003).
If none fit, set node_id to null and confidence to 0.0.
"""


def _format_candidates(candidates: list[dict]) -> str:
    lines = []
    for c in candidates:
        line = (
            f"id={c['node_id']} ({c['similarity']:.2f}) "
            f"name=\"{c['name']}\" desc=\"{c.get('description', '')[:80]}\""
        )
        lines.append(line)
    return "\n".join(lines)


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    match = re.search(r"\{[^{}]+\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def disambiguate(
    title: str,
    excerpt: str,
    candidates: list[dict],
) -> dict | None:
    """
    candidates: list of {node_id, name, description, aliases_str, similarity}
    Returns: {node_id, confidence, reason} or None if Mistral can't decide.
    """
    if not candidates:
        return None

    prompt = PROMPT_TEMPLATE.format(
        title=title[:150],
        excerpt=excerpt[:400],
        candidates_text=_format_candidates(candidates[:8]),
    )

    try:
        resp = httpx.post(
            OLLAMA_GENERATE,
            json={"model": ROUTING_MODEL, "prompt": prompt, "stream": False},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")
    except Exception as e:
        logger.warning(f"Mistral disambiguate failed: {e}")
        return None

    result = _extract_json(raw)
    if not result:
        logger.debug(f"Mistral returned unparseable response: {raw[:200]}")
        return None

    node_id = result.get("node_id")
    if isinstance(node_id, str):
        if node_id.startswith("id="):
            node_id = node_id[3:]
        if node_id.lower() in ("null", "none", ""):
            node_id = None
    confidence = float(result.get("confidence", 0.0))

    if not node_id or confidence < 0.60:
        return None

    valid_ids = {c["node_id"] for c in candidates}
    if node_id not in valid_ids:
        logger.debug(f"Mistral hallucinated node_id={node_id}, ignoring")
        return None

    return {
        "node_id": node_id,
        "confidence": confidence,
        "reason": str(result.get("reason", ""))[:200],
        "method": "mistral",
    }
