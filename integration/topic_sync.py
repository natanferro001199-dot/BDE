"""
topic_sync.py — Syncs BDE Tier 1 hypotheses into news-sentiment's topic watch list.

When BDE promotes a hypothesis to Tier 1, its keywords are added as a topic in
news-sentiment so financial media coverage is automatically tracked.

Important limitations:
  - news-sentiment's `load_settings()` runs once at startup. Writing a new topic
    here does NOT take effect until news-sentiment is restarted (no hot-reload).
  - Writes are atomic (temp file + os.replace) so a crash can't corrupt the YAML.
  - Manual topics are always preserved — only BDE-managed topics are replaced.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger

try:
    import yaml
except ImportError:
    raise ImportError("PyYAML is required: pip install PyYAML")

NS_CONFIG_PATH = Path(
    os.getenv(
        "NS_CONFIG_PATH",
        Path(__file__).resolve().parents[2] / "config" / "settings.yaml",
    )
)
NS_CONFIG_EXAMPLE = (
    Path(__file__).resolve().parents[2] / "config" / "settings.example.yaml"
)

_BDE_MARKER = "bde_managed"


def _load(path: Path) -> dict[str, Any]:
    src = path if path.exists() else NS_CONFIG_EXAMPLE
    with open(src, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_atomic(data: dict[str, Any], path: Path) -> None:
    """Write YAML atomically: write to temp file then rename.
    Prevents partial writes from corrupting settings.yaml on crash or disk-full.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=".tmp_", suffix=".yaml"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        os.replace(tmp_path, path)  # atomic on same filesystem
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def sync_tier1_hypotheses(
    hypotheses: list[dict],
    config_path: Path = NS_CONFIG_PATH,
) -> None:
    """
    Replace all BDE-managed topics in news-sentiment with current Tier 1 hypotheses.
    Manual topics are preserved. Writes are atomic.

    NOTE: news-sentiment requires a restart to pick up new topics.

    Args:
        hypotheses: list of dicts with keys: id, statement, keywords
    """
    data = _load(config_path)
    manual = [t for t in data.get("topics", []) if not t.get(_BDE_MARKER)]
    bde_topics = [
        {
            "name": f"BDE {h['id']}",
            "keywords": [k.lower() for k in h["keywords"]],
            _BDE_MARKER: True,
            "bde_statement": h["statement"][:120],
        }
        for h in hypotheses
    ]

    data["topics"] = manual + bde_topics
    _save_atomic(data, config_path)
    logger.info(
        f"Synced {len(bde_topics)} BDE Tier 1 hypotheses to {config_path}. "
        f"Manual topics preserved: {len(manual)}. "
        "Restart news-sentiment for changes to take effect."
    )


def remove_hypothesis(
    hypothesis_id: str,
    config_path: Path = NS_CONFIG_PATH,
) -> bool:
    """
    Remove a single hypothesis from news-sentiment's watch list.
    Returns True if found and removed, False if it wasn't there.
    """
    data = _load(config_path)
    before = data.get("topics", [])
    after = [t for t in before if t.get("name") != f"BDE {hypothesis_id}"]

    if len(before) == len(after):
        logger.debug(f"{hypothesis_id} not in news-sentiment topics — nothing removed")
        return False

    data["topics"] = after
    _save_atomic(data, config_path)
    logger.info(f"Removed BDE {hypothesis_id} from news-sentiment watch list")
    return True


def list_bde_topics(config_path: Path = NS_CONFIG_PATH) -> list[dict]:
    """Return all currently synced BDE topics from news-sentiment's config."""
    data = _load(config_path)
    return [t for t in data.get("topics", []) if t.get(_BDE_MARKER)]
