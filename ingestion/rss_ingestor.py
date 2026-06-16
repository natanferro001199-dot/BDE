"""
rss_ingestor.py — Fetches articles from technical RSS feeds on semiconductor and AI hardware topics.

Sources (Tier 1-2): SemiAnalysis, IEEE Spectrum, EE Times, Tom's Hardware, AnandTech, WikiChip.
Runs every 6h via Celery beat.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
from loguru import logger

from ingestion.base import Document, IngestStore

FEEDS = [
    # Tier 1-2 — specialist technical press
    {"name": "semianalysis",     "url": "https://www.semianalysis.com/feed",                              "tier": 1},
    {"name": "ieee_spectrum",    "url": "https://spectrum.ieee.org/feeds/feed.rss",                       "tier": 1},
    {"name": "eetimes",          "url": "https://www.eetimes.com/feed/",                                  "tier": 1},
    {"name": "tomshardware",     "url": "https://www.tomshardware.com/feeds/all",                         "tier": 2},
    {"name": "anandtech",        "url": "https://www.anandtech.com/rss/rssfeeds.aspx",                   "tier": 2},
    {"name": "thechipletter",    "url": "https://www.thechipletter.com/feed",                             "tier": 1},
    {"name": "semiconductor_eng","url": "https://semiengineering.com/feed/",                              "tier": 1},
    {"name": "wikichip_news",    "url": "https://fuse.wikichip.org/feed/",                                "tier": 1},
    {"name": "edn_network",      "url": "https://www.edn.com/feed/",                                     "tier": 2},
    # Tier 3 — US mainstream financial / technology press
    {"name": "nyt_technology",   "url": "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",   "tier": 3},
    {"name": "nyt_business",     "url": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",     "tier": 3},
    {"name": "nyt_economy",      "url": "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml",      "tier": 3},
    {"name": "reuters_tech",     "url": "https://feeds.reuters.com/reuters/technologyNews",               "tier": 3},
    {"name": "reuters_business", "url": "https://feeds.reuters.com/reuters/businessNews",                 "tier": 3},
    {"name": "ap_technology",    "url": "https://apnews.com/apf-technology",                              "tier": 3},
    {"name": "washpost_tech",    "url": "https://feeds.washingtonpost.com/rss/business/technology",       "tier": 3},
    {"name": "wsj_markets",      "url": "https://feeds.a.dowjones.com/rss/RSSMarketsMain.xml",            "tier": 3},
]

KEYWORDS = [
    "semiconductor", "chip", "fab", "foundry", "TSMC", "ASML", "NVIDIA", "AMD", "Intel",
    "HBM", "memory", "packaging", "CoWoS", "EUV", "lithography", "supply chain",
    "shortage", "capacity", "wafer", "AI hardware", "GPU", "accelerator",
    "bottleneck", "geopolit", "export control", "CHIPS Act", "Samsung", "SK Hynix",
    "power semiconductor", "SiC", "GaN", "substrate", "ABF",
]


def _is_relevant(title: str, summary: str) -> bool:
    text = (title + " " + summary).lower()
    return any(kw.lower() in text for kw in KEYWORDS)


def _parse_date(entry: dict) -> str:
    for field in ("published", "updated"):
        raw = entry.get(field)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                return dt.astimezone(timezone.utc).isoformat()
            except Exception:
                try:
                    return datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S").isoformat() + "Z"
                except Exception:
                    pass
    return datetime.now(timezone.utc).isoformat()


def fetch_feed(feed: dict, store: IngestStore) -> int:
    name = feed["name"]
    try:
        parsed = feedparser.parse(feed["url"])
        if parsed.bozo and not parsed.entries:
            logger.warning(f"RSS {name}: feed parse error — {parsed.bozo_exception}")
            return 0
    except Exception as e:
        logger.warning(f"RSS {name}: {e}")
        return 0

    saved = 0
    for entry in parsed.entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "")
        summary = re.sub(r"<[^>]+>", " ", entry.get("summary", "") or "").strip()
        content_list = entry.get("content", [])
        text = content_list[0].get("value", "") if content_list else summary
        text = re.sub(r"<[^>]+>", " ", text).strip()[:3000]

        if not _is_relevant(title, summary):
            continue

        uid_raw = entry.get("id") or link or title
        uid = f"rss_{name}:{hashlib.sha256(uid_raw.encode()).hexdigest()[:16]}"

        doc = Document(
            uid=uid,
            title=title,
            text=text or summary or title,
            url=link,
            source=f"rss_{name}",
            ias_tier=feed["tier"],
            published_at=_parse_date(entry),
            metadata={
                "feed": name,
                "feed_url": feed["url"],
                "tags": [t.get("term", "") for t in entry.get("tags", [])],
            },
        )
        if store.save(doc):
            saved += 1

    return saved


def run() -> dict:
    store = IngestStore()
    total = 0
    for feed in FEEDS:
        n = fetch_feed(feed, store)
        if n:
            logger.info(f"RSS {feed['name']}: {n} new articles")
        total += n

    counts = store.counts()
    logger.info(f"RSS ingestor done. New: {total}. Queue: {counts}")
    return {"new": total, **counts}


if __name__ == "__main__":
    print(run())
