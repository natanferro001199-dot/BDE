"""
document_processor.py — Pulls documents from the ingest queue and prepares them for entity resolution.

Pipeline:
  1. Pull pending documents from IngestStore
  2. Normalise text (clean HTML, truncate, deduplicate whitespace)
  3. Extract candidate entity mentions (regex against taxonomy names)
  4. Push enriched doc to the entity_resolution_queue in Redis
  5. Mark document as processed in IngestStore

Phase 3 (EntityResolver) will consume from entity_resolution_queue.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import redis
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import REDIS_URL
from ingestion.base import IngestStore

MAX_TEXT_TOKENS = 1500  # ~2000 words; embedding context window
ENTITY_QUEUE_KEY = "bde:entity_resolution_queue"
BATCH_SIZE = 50


def _clean_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_TEXT_TOKENS * 5]


def _load_taxonomy_names(taxonomy_path: Path) -> list[str]:
    if not taxonomy_path.exists():
        return []
    data = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    names = []
    for c in data.get("concepts", []):
        names.append(c["name"])
        names.extend(c.get("aliases", []))
    return list(set(names))


def _extract_mentions(text: str, names: list[str]) -> list[str]:
    found = []
    lower = text.lower()
    for name in names:
        if len(name) < 3:
            continue
        if re.search(r"\b" + re.escape(name.lower()) + r"\b", lower):
            found.append(name)
    return found


def process_batch(batch_size: int = BATCH_SIZE) -> dict:
    store = IngestStore()
    r = redis.from_url(REDIS_URL, decode_responses=True)

    taxonomy_path = Path(__file__).resolve().parents[1] / "taxonomy" / "taxonomy.json"
    names = _load_taxonomy_names(taxonomy_path)
    logger.info(f"Loaded {len(names)} taxonomy names for mention extraction")

    docs = store.pending(limit=batch_size)
    if not docs:
        logger.debug("No pending documents to process")
        return {"processed": 0}

    processed_uids = []
    for doc in docs:
        text = _clean_text(doc.get("text") or doc.get("title") or "")
        mentions = _extract_mentions(text, names)

        payload = {
            "uid": doc["uid"],
            "source": doc["source"],
            "title": doc["title"],
            "url": doc["url"],
            "ias_tier": doc["ias_tier"],
            "published_at": doc["published_at"],
            "text": text,
            "candidate_entities": mentions,
            "metadata": json.loads(doc.get("metadata") or "{}"),
        }
        r.lpush(ENTITY_QUEUE_KEY, json.dumps(payload))
        processed_uids.append(doc["uid"])

    store.mark_processed(processed_uids)
    logger.info(
        f"Processed {len(processed_uids)} documents → {ENTITY_QUEUE_KEY} "
        f"(queue depth: {r.llen(ENTITY_QUEUE_KEY)})"
    )
    return {
        "processed": len(processed_uids),
        "queue_depth": r.llen(ENTITY_QUEUE_KEY),
        "remaining_pending": store.counts()["pending"],
    }


def queue_depth() -> int:
    r = redis.from_url(REDIS_URL, decode_responses=True)
    return r.llen(ENTITY_QUEUE_KEY)


def stats() -> dict:
    store = IngestStore()
    return {**store.counts(), "entity_queue_depth": queue_depth()}


if __name__ == "__main__":
    print(process_batch())
