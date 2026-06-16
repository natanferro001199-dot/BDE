"""
hn_ingestor.py — Fetches Hacker News stories via Algolia API.

Searches for semiconductor, AI hardware, and supply chain topics.
Runs every 4h via Celery beat.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests
from loguru import logger

from ingestion.base import Document, IngestStore

ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"

QUERIES = [
    "semiconductor supply chain",
    "TSMC chip",
    "NVIDIA GPU shortage",
    "AI hardware bottleneck",
    "HBM memory",
    "chip shortage",
    "EUV lithography",
    "ASML",
    "CoWoS packaging",
    "AI accelerator",
    "foundry capacity",
    "wafer shortage",
    "Intel fab",
    "Samsung foundry",
]

IAS_TIER = 1
MIN_POINTS = 10


def fetch_query(query: str, since_ts: int, store: IngestStore) -> int:
    params = {
        "query": query,
        "tags": "story",
        "numericFilters": f"created_at_i>{since_ts},points>{MIN_POINTS}",
        "hitsPerPage": 30,
    }
    try:
        resp = requests.get(ALGOLIA_URL, params=params, timeout=15)
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
    except Exception as e:
        logger.warning(f"HN query '{query}': {e}")
        return 0

    saved = 0
    for hit in hits:
        story_id = hit.get("objectID", "")
        uid = f"hn:{story_id}"
        title = hit.get("title") or hit.get("story_title") or ""
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
        text = hit.get("story_text") or hit.get("comment_text") or title
        created_at = hit.get("created_at") or datetime.now(timezone.utc).isoformat()

        doc = Document(
            uid=uid,
            title=title,
            text=text[:3000],
            url=url,
            source="hn",
            ias_tier=IAS_TIER,
            published_at=created_at,
            metadata={
                "points": hit.get("points", 0),
                "num_comments": hit.get("num_comments", 0),
                "author": hit.get("author", ""),
                "query": query,
            },
        )
        if store.save(doc):
            saved += 1

    return saved


def run(lookback_hours: int = 48) -> dict:
    store = IngestStore()
    since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    since_ts = int(since.timestamp())
    total = 0

    seen_ids: set[str] = set()
    for query in QUERIES:
        n = fetch_query(query, since_ts, store)
        total += n

    counts = store.counts()
    logger.info(f"HN ingestor done. New: {total}. Queue: {counts}")
    return {"new": total, **counts}


if __name__ == "__main__":
    print(run())
