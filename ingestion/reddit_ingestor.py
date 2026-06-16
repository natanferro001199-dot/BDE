"""
reddit_ingestor.py — Fetches supply-chain signal from Reddit via PRAW.

Subreddits: r/chipdesign, r/semiconductors, r/SecurityAnalysis,
            r/hardware, r/MachineLearning, r/singularity

Requires: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT env vars.
Free Reddit API credentials: https://www.reddit.com/prefs/apps (script type).

Falls back to public JSON API (no auth) if PRAW creds not set — limited to 25 posts/sub.
Runs every 6h via Celery beat.
"""
from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from loguru import logger

from ingestion.base import Document, IngestStore

SUBREDDITS = [
    {"name": "chipdesign",       "tier": 1},
    {"name": "semiconductors",   "tier": 1},
    {"name": "SecurityAnalysis", "tier": 2},
    {"name": "hardware",         "tier": 2},
    {"name": "MachineLearning",  "tier": 2},
    {"name": "singularity",      "tier": 2},
    {"name": "StockMarket",      "tier": 3},
]

KEYWORDS = [
    "semiconductor", "chip", "fab", "foundry", "tsmc", "asml", "nvidia", "amd",
    "hbm", "memory", "packaging", "cowos", "euv", "lithography", "supply chain",
    "shortage", "wafer", "ai hardware", "gpu", "accelerator", "bottleneck",
    "export control", "chips act", "samsung", "sk hynix", "sic", "gan",
    "substrate", "abf", "geopolit", "taiwan", "china", "intel",
]

CLIENT_ID     = os.getenv("REDDIT_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
USER_AGENT    = os.getenv("REDDIT_USER_AGENT", "BDE-Research-Bot/1.0 (research use)")
MIN_SCORE     = 5
PUBLIC_LIMIT  = 25


def _is_relevant(title: str, text: str) -> bool:
    combined = (title + " " + text).lower()
    return any(kw in combined for kw in KEYWORDS)


def _fetch_public(subreddit: str, lookback_hours: int) -> list[dict]:
    """Fallback: public Reddit JSON API, no auth required."""
    url = f"https://www.reddit.com/r/{subreddit}/new.json"
    params = {"limit": PUBLIC_LIMIT}
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        posts = resp.json()["data"]["children"]
    except Exception as e:
        logger.warning(f"Reddit public API r/{subreddit}: {e}")
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).timestamp()
    results = []
    for post in posts:
        d = post["data"]
        if d.get("created_utc", 0) < cutoff:
            continue
        if d.get("score", 0) < MIN_SCORE:
            continue
        results.append({
            "id": d["id"],
            "title": d.get("title", ""),
            "text": d.get("selftext", "") or d.get("url", ""),
            "url": f"https://www.reddit.com{d.get('permalink', '')}",
            "score": d.get("score", 0),
            "num_comments": d.get("num_comments", 0),
            "created_utc": d.get("created_utc", 0),
            "subreddit": subreddit,
            "author": d.get("author", ""),
        })
    return results


def _fetch_praw(subreddit: str, lookback_hours: int) -> list[dict]:
    try:
        import praw
        reddit = praw.Reddit(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            user_agent=USER_AGENT,
        )
        sub = reddit.subreddit(subreddit)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).timestamp()
        results = []
        for post in sub.new(limit=100):
            if post.created_utc < cutoff:
                break
            if post.score < MIN_SCORE:
                continue
            results.append({
                "id": post.id,
                "title": post.title,
                "text": post.selftext or post.url,
                "url": f"https://www.reddit.com{post.permalink}",
                "score": post.score,
                "num_comments": post.num_comments,
                "created_utc": post.created_utc,
                "subreddit": subreddit,
                "author": str(post.author) if post.author else "",
            })
        return results
    except Exception as e:
        logger.warning(f"PRAW r/{subreddit}: {e} — falling back to public API")
        return _fetch_public(subreddit, lookback_hours)


def fetch_subreddit(sub_cfg: dict, store: IngestStore, lookback_hours: int) -> int:
    name = sub_cfg["name"]
    tier = sub_cfg["tier"]

    if CLIENT_ID and CLIENT_SECRET:
        posts = _fetch_praw(name, lookback_hours)
    else:
        posts = _fetch_public(name, lookback_hours)

    saved = 0
    for post in posts:
        title = post["title"]
        text = post["text"][:3000]

        if not _is_relevant(title, text):
            continue

        uid = f"reddit:{post['id']}"
        published = datetime.fromtimestamp(post["created_utc"], tz=timezone.utc).isoformat()

        doc = Document(
            uid=uid,
            title=title,
            text=text or title,
            url=post["url"],
            source=f"reddit_r_{name.lower()}",
            ias_tier=tier,
            published_at=published,
            metadata={
                "subreddit": name,
                "score": post["score"],
                "num_comments": post["num_comments"],
                "author": post["author"],
            },
        )
        if store.save(doc):
            saved += 1

    time.sleep(2)  # Reddit rate limit
    return saved


def run(lookback_hours: int = 48) -> dict:
    store = IngestStore()
    total = 0
    for sub_cfg in SUBREDDITS:
        n = fetch_subreddit(sub_cfg, store, lookback_hours)
        if n:
            logger.info(f"Reddit r/{sub_cfg['name']}: {n} new posts")
        total += n

    counts = store.counts()
    logger.info(f"Reddit ingestor done. New: {total}. Queue: {counts}")
    return {"new": total, **counts}


if __name__ == "__main__":
    print(run())
