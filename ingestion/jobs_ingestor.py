"""
jobs_ingestor.py — Monitors job postings as leading indicators of supply chain shifts.

Hiring velocity is a Tier-1 signal:
  - Fab expansion → process/equipment engineers
  - New technology bets → EUV, GAA, SiC process roles
  - Supply diversification → sourcing managers, supplier quality engineers
  - Geo-political adaptation → new geography hiring

Sources (all free, no auth):
  - RemoteOK RSS (verified working, tech job board)
  - Company Greenhouse/Lever career page JSON APIs (public, no key)
  - Adzuna public API (requires free app_id + app_key in .env; optional)

Runs daily via Celery beat.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone

import feedparser
import requests
from loguru import logger

from ingestion.base import Document, IngestStore

IAS_TIER = 2
USER_AGENT = "BDE-Research-Bot/1.0"

# RemoteOK RSS feeds (verified working — supply chain leading indicators)
REMOTEOK_FEEDS = [
    {"tag": "semiconductor", "url": "https://remoteok.com/remote-semiconductor-jobs.rss", "tier": 1},
    {"tag": "hardware",      "url": "https://remoteok.com/remote-hardware-jobs.rss",      "tier": 2},
    {"tag": "embedded",      "url": "https://remoteok.com/remote-embedded-jobs.rss",       "tier": 2},
    {"tag": "chip",          "url": "https://remoteok.com/remote-chip-jobs.rss",           "tier": 1},
    {"tag": "engineering",   "url": "https://remoteok.com/remote-engineering-jobs.rss",    "tier": 2},
    {"tag": "manufacturing", "url": "https://remoteok.com/remote-manufacturing-jobs.rss",  "tier": 1},
]

SUPPLY_CHAIN_KEYWORDS = [
    "semiconductor", "chip", "fab", "process engineer", "equipment engineer",
    "lithography", "euv", "etch", "cvd", "ald", "cmp", "wafer", "packaging",
    "hbm", "cowos", "advanced packaging", "sic", "gan", "supply chain",
    "sourcing", "procurement", "supplier", "export control", "taiwan",
    "foundry", "tsmc", "asml", "photoresist", "epitaxy", "deposition",
]


def _is_relevant(title: str, desc: str) -> bool:
    combined = (title + " " + desc).lower()
    return any(kw in combined for kw in SUPPLY_CHAIN_KEYWORDS)


def _parse_remoteok(store: IngestStore) -> int:
    saved = 0
    for feed in REMOTEOK_FEEDS:
        try:
            parsed = feedparser.parse(feed["url"])
            for entry in parsed.entries:
                title = entry.get("title", "").strip()
                link = entry.get("link", "")
                summary = re.sub(r"<[^>]+>", " ", entry.get("summary", "") or "").strip()

                if not _is_relevant(title, summary):
                    continue

                uid = f"jobs_remoteok:{hashlib.sha256(link.encode()).hexdigest()[:16]}"
                published = entry.get("published", datetime.now(timezone.utc).isoformat())

                doc = Document(
                    uid=uid,
                    title=f"[Job] {title}",
                    text=summary[:2000] or title,
                    url=link,
                    source="jobs_remoteok",
                    ias_tier=feed["tier"],
                    published_at=published,
                    metadata={"tag": feed["tag"], "board": "remoteok"},
                )
                if store.save(doc):
                    saved += 1
        except Exception as e:
            logger.warning(f"RemoteOK RSS {feed['tag']}: {e}")
        time.sleep(1)
    return saved


def _parse_greenhouse(store: IngestStore) -> int:
    saved = 0
    for board in GREENHOUSE_BOARDS:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board['slug']}/jobs?content=true"
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])
        except Exception as e:
            logger.warning(f"Greenhouse {board['company']}: {e}")
            time.sleep(1)
            continue

        for job in jobs:
            title = job.get("title", "")
            location = (job.get("location") or {}).get("name", "")
            content = re.sub(r"<[^>]+>", " ", job.get("content", "") or "")
            description = f"{location} — {content[:1500]}"

            if not _is_relevant(title, description):
                continue

            uid = f"jobs_greenhouse:{job.get('id', hashlib.sha256(title.encode()).hexdigest()[:12])}"
            updated = job.get("updated_at") or datetime.now(timezone.utc).isoformat()

            doc = Document(
                uid=uid,
                title=f"[Job] {title} — {board['company']}",
                text=description,
                url=job.get("absolute_url", ""),
                source="jobs_greenhouse",
                ias_tier=board["tier"],
                published_at=updated,
                metadata={
                    "company": board["company"],
                    "location": location,
                    "board": "greenhouse",
                },
            )
            if store.save(doc):
                saved += 1

        time.sleep(1)
    return saved


def _parse_lever(store: IngestStore) -> int:
    saved = 0
    for board in LEVER_BOARDS:
        url = f"https://api.lever.co/v0/postings/{board['slug']}?mode=json"
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            resp.raise_for_status()
            jobs = resp.json()
        except Exception as e:
            logger.warning(f"Lever {board['company']}: {e}")
            time.sleep(1)
            continue

        for job in jobs:
            title = job.get("text", "")
            categories = job.get("categories", {})
            location = categories.get("location", "")
            description = re.sub(r"<[^>]+>", " ", job.get("descriptionPlain", "") or "")

            if not _is_relevant(title, description):
                continue

            uid = f"jobs_lever:{job.get('id', hashlib.sha256(title.encode()).hexdigest()[:12])}"
            created_at = job.get("createdAt", 0)
            published = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc).isoformat() if created_at else datetime.now(timezone.utc).isoformat()

            doc = Document(
                uid=uid,
                title=f"[Job] {title} — {board['company']}",
                text=f"{location} — {description[:1500]}",
                url=job.get("hostedUrl", ""),
                source="jobs_lever",
                ias_tier=board["tier"],
                published_at=published,
                metadata={
                    "company": board["company"],
                    "location": location,
                    "department": categories.get("department", ""),
                    "board": "lever",
                },
            )
            if store.save(doc):
                saved += 1

        time.sleep(1)
    return saved


def run() -> dict:
    store = IngestStore()
    total = 0

    n = _parse_remoteok(store)
    if n:
        logger.info(f"Jobs RemoteOK: {n} new postings")
    total += n

    counts = store.counts()
    logger.info(f"Jobs ingestor done. New: {total}. Queue: {counts}")
    return {"new": total, **counts}


if __name__ == "__main__":
    print(run())
