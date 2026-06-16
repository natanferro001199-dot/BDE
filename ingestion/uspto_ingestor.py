"""
uspto_ingestor.py — Monitors USPTO patents for supply chain signal via PatentsView API.

Free API at https://api.patentsview.org — no key required, rate limit 45 req/min.

Tracks patent filings from key semiconductor companies as leading indicators of:
  - R&D investment direction (new process nodes, materials, packaging)
  - Technology development velocity (patent velocity = proprietary moat proxy)
  - Competitive dynamics (who's filing where)

Runs weekly via Celery beat.
"""
from __future__ import annotations

import hashlib
import time
from datetime import date, timedelta

import requests
from loguru import logger

from ingestion.base import Document, IngestStore

# Note: search.patentsview.org (new API) may not resolve on all networks.
# Fallback to api.patentsview.org (older endpoint, still functional on most networks).
API_URL = "https://api.patentsview.org/patents/query"
IAS_TIER = 1

ASSIGNEES = [
    "Taiwan Semiconductor Manufacturing",
    "ASML Netherlands",
    "NVIDIA Corporation",
    "Advanced Micro Devices",
    "Intel Corporation",
    "SK Hynix",
    "Samsung Electronics",
    "Micron Technology",
    "Applied Materials",
    "Lam Research",
    "KLA Corporation",
    "Entegris",
    "Ajinomoto",
    "IMEC",
    "Qualcomm",
    "Broadcom",
]

SUPPLY_CHAIN_CPC_CODES = [
    "H01L21",  # Semiconductor device manufacture
    "H01L23",  # Semiconductor device details/packaging
    "H01L25",  # Multi-layer chips / 3D packaging
    "H01L27",  # Integrated circuits
    "G03F7",   # Photolithography / EUV
    "H01L29",  # Semiconductor devices (transistors, diodes)
    "C30B",    # Crystal growth (wafer production)
    "H01L31",  # Photovoltaics / compound semiconductors
]

KEYWORDS_IN_ABSTRACT = [
    "extreme ultraviolet", "EUV", "CoWoS", "HBM", "high bandwidth memory",
    "advanced packaging", "chiplet", "3D stacking", "gate-all-around",
    "silicon carbide", "gallium nitride", "ABF substrate",
    "supply chain", "sole source", "single source",
]

MAX_PATENTS_PER_QUERY = 50


def _query_by_assignee(assignee: str, days_back: int) -> list[dict]:
    start_date = (date.today() - timedelta(days=days_back)).strftime("%Y%m%d")
    query = {
        "q": {
            "_and": [
                {"_contains": {"assignee_organization": assignee}},
                {"_gte": {"patent_date": start_date}},
            ]
        },
        "f": ["patent_id", "patent_title", "patent_abstract", "patent_date",
              "assignee_organization"],
        "o": {"per_page": MAX_PATENTS_PER_QUERY},
        "s": [{"patent_date": "desc"}],
    }
    try:
        resp = requests.post(API_URL, json=query, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        return data.get("patents") or []
    except Exception as e:
        logger.warning(f"USPTO query for '{assignee}': {e}")
        return []


def _is_relevant(title: str, abstract: str) -> bool:
    combined = (title + " " + abstract).lower()
    return any(kw.lower() in combined for kw in KEYWORDS_IN_ABSTRACT)


def run(days_back: int = 90) -> dict:
    store = IngestStore()
    total = 0

    for assignee in ASSIGNEES:
        patents = _query_by_assignee(assignee, days_back)
        for patent in patents:
            title = patent.get("patent_title") or ""
            abstract = patent.get("patent_abstract") or ""

            if not _is_relevant(title, abstract):
                continue

            pid = patent.get("patent_id") or hashlib.sha256(title.encode()).hexdigest()[:12]
            uid = f"uspto:{pid}"
            patent_date = patent.get("patent_date") or ""

            doc = Document(
                uid=uid,
                title=f"[Patent] {title}",
                text=abstract[:3000] or title,
                url=f"https://patents.google.com/patent/US{pid}",
                source="uspto",
                ias_tier=IAS_TIER,
                published_at=f"{patent_date}T00:00:00Z" if patent_date else "",
                metadata={
                    "patent_id": pid,
                    "assignee": assignee,
                },
            )
            if store.save(doc):
                total += 1
                logger.debug(f"USPTO: {doc.title[:80]}")

        time.sleep(1.5)  # PatentsView rate limit

    counts = store.counts()
    logger.info(f"USPTO ingestor done. New: {total}. Queue: {counts}")
    return {"new": total, **counts}


if __name__ == "__main__":
    print(run())
