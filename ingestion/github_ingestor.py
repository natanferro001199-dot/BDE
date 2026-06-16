"""
github_ingestor.py — Fetches recent GitHub issues and PRs from AI/semiconductor repos.

Sources (Tier 1): supply chain signals from open-source AI infrastructure projects.
Runs every 4h via Celery beat.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from loguru import logger

from ingestion.base import Document, IngestStore

REPOS = [
    "vllm-project/vllm",
    "pytorch/pytorch",
    "NVIDIA/nccl",
    "huggingface/transformers",
    "openai/triton",
    "microsoft/DeepSpeed",
    "NVIDIA/cuda-quantum",
    "google/jax",
    "openai/openai-python",
    "huggingface/accelerate",
    "sgl-project/sglang",
    "lm-sys/fastchat",
]

SUPPLY_CHAIN_KEYWORDS = [
    "chip", "gpu", "memory", "bandwidth", "cuda", "hardware", "capacity",
    "shortage", "supply", "hbm", "nvlink", "infiniband", "network", "bottleneck",
    "latency", "throughput", "oom", "out of memory", "allocation", "driver",
    "firmware", "nvme", "pcie", "interconnect", "cluster", "topology", "fabric",
    "tsmc", "nvidia", "amd", "intel", "a100", "h100", "h200", "b200", "mi300",
    "tpu", "trainium", "inferentia", "wafer", "node", "process",
]

GH_API = "https://api.github.com"
IAS_TIER = 1


def _headers() -> dict:
    token = os.getenv("GITHUB_TOKEN")
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _is_relevant(title: str, body: str) -> bool:
    text = (title + " " + (body or "")).lower()
    return any(kw in text for kw in SUPPLY_CHAIN_KEYWORDS)


def fetch_repo(repo: str, since: datetime, store: IngestStore) -> int:
    saved = 0
    for kind in ("issues", "pulls"):
        url = f"{GH_API}/repos/{repo}/{kind}"
        params = {
            "state": "all",
            "sort": "updated",
            "direction": "desc",
            "per_page": 50,
            "since": since.isoformat(),
        }
        try:
            resp = requests.get(url, headers=_headers(), params=params, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"GitHub {repo}/{kind}: {e}")
            continue

        for item in resp.json():
            title = item.get("title", "")
            body = item.get("body") or ""
            if not _is_relevant(title, body):
                continue

            uid = f"github:{repo}:{item['number']}:{kind[:-1]}"
            doc = Document(
                uid=uid,
                title=f"[{repo}] {title}",
                text=(body[:3000] if body else title),
                url=item.get("html_url", ""),
                source="github",
                ias_tier=IAS_TIER,
                published_at=item.get("updated_at") or item.get("created_at", ""),
                metadata={
                    "repo": repo,
                    "number": item["number"],
                    "kind": kind[:-1],
                    "state": item.get("state"),
                    "labels": [l["name"] for l in item.get("labels", [])],
                    "comments": item.get("comments", 0),
                },
            )
            if store.save(doc):
                saved += 1

    return saved


def run(lookback_hours: int = 96) -> dict:
    store = IngestStore()
    since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    total = 0
    for repo in REPOS:
        n = fetch_repo(repo, since, store)
        if n:
            logger.info(f"GitHub {repo}: {n} new documents")
        total += n
    counts = store.counts()
    logger.info(f"GitHub ingestor done. New: {total}. Queue: {counts}")
    return {"new": total, **counts}


if __name__ == "__main__":
    print(run())
