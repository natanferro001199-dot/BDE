"""
arxiv_ingestor.py — Fetches recent arXiv papers on AI hardware and semiconductor topics.

Categories: cs.AR (Hardware Architecture), cs.DC (Distributed Computing), cs.LG (Machine Learning).
Runs daily via Celery beat.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from urllib.parse import quote

import requests
from loguru import logger

from ingestion.base import Document, IngestStore

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom"}
IAS_TIER = 2

QUERIES = [
    # Hardware architecture
    ('cat:cs.AR AND (ti:"GPU" OR ti:"TPU" OR ti:"HBM" OR ti:"memory" OR ti:"accelerator")', "cs.AR"),
    ('cat:cs.AR AND (ti:"inference" OR ti:"training" OR ti:"transformer" OR ti:"attention")', "cs.AR"),
    # Distributed/systems
    ('cat:cs.DC AND (ti:"GPU cluster" OR ti:"collective" OR ti:"NVLink" OR ti:"InfiniBand")', "cs.DC"),
    ('cat:cs.DC AND (ti:"memory" OR ti:"bandwidth" OR ti:"interconnect" OR ti:"network topology")', "cs.DC"),
    # ML hardware efficiency
    ('cat:cs.LG AND (ti:"efficient" OR ti:"hardware" OR ti:"quantization" OR ti:"sparse")', "cs.LG"),
    # Semiconductor/manufacturing
    ('cat:cs.AR AND (ab:"DRAM" OR ab:"HBM" OR ab:"SRAM" OR ab:"cache" OR ab:"memory wall")', "cs.AR"),
]

MAX_RESULTS = 25


def _parse_entry(entry: ET.Element) -> dict | None:
    try:
        arxiv_id = entry.find("atom:id", NS).text.split("/abs/")[-1].strip()
        title = entry.find("atom:title", NS).text.strip().replace("\n", " ")
        summary = entry.find("atom:summary", NS).text.strip().replace("\n", " ")
        published = entry.find("atom:published", NS).text.strip()
        authors = [
            a.find("atom:name", NS).text
            for a in entry.findall("atom:author", NS)
        ]
        link = f"https://arxiv.org/abs/{arxiv_id}"
        return {
            "id": arxiv_id,
            "title": title,
            "summary": summary,
            "published": published,
            "authors": authors,
            "url": link,
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
        }
    except Exception:
        return None


def fetch_query(query: str, category: str, store: IngestStore, days_back: int) -> int:
    cutoff = (date.today() - timedelta(days=days_back)).strftime("%Y%m%d")
    full_query = f"({query}) AND submittedDate:[{cutoff}0000 TO 99991231235959]"

    params = {
        "search_query": full_query,
        "max_results": MAX_RESULTS,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    try:
        resp = requests.get(ARXIV_API, params=params, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception as e:
        logger.warning(f"arXiv query '{category}': {e}")
        return 0

    entries = root.findall("atom:entry", NS)
    saved = 0
    for entry in entries:
        parsed = _parse_entry(entry)
        if not parsed:
            continue
        uid = f"arxiv:{parsed['id']}"
        doc = Document(
            uid=uid,
            title=parsed["title"],
            text=parsed["summary"][:3000],
            url=parsed["url"],
            source="arxiv",
            ias_tier=IAS_TIER,
            published_at=parsed["published"],
            metadata={
                "arxiv_id": parsed["id"],
                "authors": parsed["authors"][:5],
                "pdf_url": parsed["pdf_url"],
                "category": category,
            },
        )
        if store.save(doc):
            saved += 1

    time.sleep(3)  # arXiv rate limit: 1 req/3s
    return saved


def run(days_back: int = 14) -> dict:
    store = IngestStore()
    total = 0
    for query, category in QUERIES:
        n = fetch_query(query, category, store, days_back)
        if n:
            logger.info(f"arXiv {category}: {n} new papers")
        total += n

    counts = store.counts()
    logger.info(f"arXiv ingestor done. New: {total}. Queue: {counts}")
    return {"new": total, **counts}


if __name__ == "__main__":
    print(run())
