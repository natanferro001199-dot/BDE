"""
embedder.py — Text embeddings via nomic-embed-text (Ollama).

For texts longer than ~2000 chars, splits into overlapping chunks and
returns the mean-pooled embedding so the full document is represented.
"""
from __future__ import annotations

import numpy as np
from loguru import logger
from ollama import Client as OllamaClient

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import OLLAMA_BASE_URL, EMBEDDING_MODEL

CHUNK_CHARS = 2000
OVERLAP_CHARS = 200
EMBED_DIM = 768

_client: OllamaClient | None = None


def _get_client() -> OllamaClient:
    global _client
    if _client is None:
        _client = OllamaClient(host=OLLAMA_BASE_URL)
    return _client


def _chunks(text: str) -> list[str]:
    if len(text) <= CHUNK_CHARS:
        return [text]
    parts = []
    start = 0
    while start < len(text):
        parts.append(text[start : start + CHUNK_CHARS])
        start += CHUNK_CHARS - OVERLAP_CHARS
    return parts


def _embed_one(text: str) -> list[float]:
    client = _get_client()
    try:
        resp = client.embeddings(model=EMBEDDING_MODEL, prompt=text[:4096])
        return resp["embedding"]
    except Exception as e:
        logger.warning(f"Embedding error: {e}")
        return [0.0] * EMBED_DIM


def embed(text: str) -> list[float]:
    """Return 768-dim embedding. Mean-pools chunk embeddings for long texts."""
    chunks = _chunks(text.strip() or " ")
    if len(chunks) == 1:
        return _embed_one(chunks[0])
    vecs = np.array([_embed_one(c) for c in chunks], dtype=np.float32)
    mean = vecs.mean(axis=0)
    norm = np.linalg.norm(mean)
    if norm > 0:
        mean /= norm
    return mean.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    return [embed(t) for t in texts]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))
