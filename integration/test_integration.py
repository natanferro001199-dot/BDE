"""Tests for the BDE <-> news-sentiment integration layer."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from integration.ns_bridge import fetch_new_articles, mark_ingested, article_count
from integration.ias_monitor import (
    WatchedHypothesis,
    check_tier34_coverage,
    should_alert,
    format_ias_alert,
    run_check,
    persist_alert,
    load_alerted_layers,
)
from integration.topic_sync import (
    sync_tier1_hypotheses,
    remove_hypothesis,
    list_bde_topics,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ns_db(tmp_path: Path, articles: list[dict]) -> Path:
    """Create a minimal news-sentiment SQLite DB with test articles."""
    db = tmp_path / "news.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE seen (
            uid TEXT PRIMARY KEY,
            title TEXT,
            url TEXT,
            source TEXT,
            sentiment_score REAL,
            sentiment_label TEXT,
            topics TEXT DEFAULT '[]',
            alerted INTEGER DEFAULT 0,
            first_seen TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.executemany(
        "INSERT INTO seen (uid, title, url, source, sentiment_score, topics, first_seen) "
        "VALUES (?,?,?,?,?,?,?)",
        [
            (
                a["uid"],
                a["title"],
                a["url"],
                a["source"],
                a.get("score", 0.0),
                a.get("topics", "[]"),
                a.get("first_seen", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
            )
            for a in articles
        ],
    )
    conn.commit()
    conn.close()
    return db


def _hyp(
    id="BN-2024-047",
    statement="ABF substrate supply will constrain CoWoS capacity through 2026",
    keywords=None,
    confidence=0.78,
    ops_score=8.7,
    awareness_layer=2,
    alerted_layers=None,
) -> WatchedHypothesis:
    return WatchedHypothesis(
        id=id,
        statement=statement,
        keywords=keywords or ["ABF", "Ajinomoto", "substrate", "CoWoS"],
        confidence=confidence,
        ops_score=ops_score,
        awareness_layer=awareness_layer,
        alerted_layers=alerted_layers if alerted_layers is not None else [],
    )


def _recent() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _old() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# ns_bridge
# ---------------------------------------------------------------------------

def test_fetch_returns_unprocessed_articles(tmp_path):
    db = _make_ns_db(tmp_path, [
        {"uid": "aaa", "title": "ABF supply tightens", "url": "https://x.com/1", "source": "Reuters"},
        {"uid": "bbb", "title": "TSMC CoWoS allocation", "url": "https://x.com/2", "source": "Bloomberg"},
    ])
    tracking = tmp_path / "tracking.db"
    articles = list(fetch_new_articles(ns_db_path=db, tracking_db_path=tracking))
    assert len(articles) == 2
    assert articles[0]["ias_tier"] == 4


def test_mark_ingested_prevents_refetch(tmp_path):
    db = _make_ns_db(tmp_path, [
        {"uid": "aaa", "title": "ABF supply tightens", "url": "https://x.com/1", "source": "Reuters"},
    ])
    tracking = tmp_path / "tracking.db"
    list(fetch_new_articles(ns_db_path=db, tracking_db_path=tracking))
    mark_ingested(["aaa"], tracking_db_path=tracking)
    assert list(fetch_new_articles(ns_db_path=db, tracking_db_path=tracking)) == []


def test_mark_ingested_empty_list_is_safe(tmp_path):
    """mark_ingested([]) must not raise."""
    tracking = tmp_path / "tracking.db"
    mark_ingested([], tracking_db_path=tracking)  # should not raise


def test_article_count(tmp_path):
    db = _make_ns_db(tmp_path, [
        {"uid": "aaa", "title": "ABF news", "url": "https://x.com/1", "source": "Reuters"},
        {"uid": "bbb", "title": "CoWoS news", "url": "https://x.com/2", "source": "Bloomberg"},
    ])
    tracking = tmp_path / "tracking.db"
    counts = article_count(ns_db_path=db, tracking_db_path=tracking)
    assert counts["total"] == 2
    assert counts["pending_bde"] == 2

    mark_ingested(["aaa"], tracking_db_path=tracking)
    counts2 = article_count(ns_db_path=db, tracking_db_path=tracking)
    assert counts2["pending_bde"] == 1


def test_missing_db_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        list(fetch_new_articles(
            ns_db_path=tmp_path / "nonexistent.db",
            tracking_db_path=tmp_path / "tracking.db",
        ))


def test_fetch_handles_empty_string_topics(tmp_path):
    """topics stored as '' (not NULL or '[]') must not raise JSONDecodeError."""
    db = tmp_path / "news.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE seen (uid TEXT PRIMARY KEY, title TEXT, url TEXT, source TEXT, "
        "sentiment_score REAL, sentiment_label TEXT, topics TEXT DEFAULT '[]', "
        "alerted INTEGER DEFAULT 0, first_seen TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO seen (uid, title, url, source, topics) VALUES (?,?,?,?,?)",
        ("uid1", "ABF news", "https://x.com/1", "Reuters", ""),
    )
    conn.commit()
    conn.close()
    tracking = tmp_path / "tracking.db"
    articles = list(fetch_new_articles(ns_db_path=db, tracking_db_path=tracking))
    assert len(articles) == 1
    assert articles[0]["topics"] == []


def test_fetch_handles_legacy_csv_topics(tmp_path):
    """topics stored as CSV ('Topic A,Topic B') must parse without crash."""
    db = tmp_path / "news.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE seen (uid TEXT PRIMARY KEY, title TEXT, url TEXT, source TEXT, "
        "sentiment_score REAL, sentiment_label TEXT, topics TEXT DEFAULT '[]', "
        "alerted INTEGER DEFAULT 0, first_seen TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO seen (uid, title, url, source, topics) VALUES (?,?,?,?,?)",
        ("uid1", "ABF news", "https://x.com/1", "Reuters", "Tech,Energy"),
    )
    conn.commit()
    conn.close()
    tracking = tmp_path / "tracking.db"
    articles = list(fetch_new_articles(ns_db_path=db, tracking_db_path=tracking))
    assert articles[0]["topics"] == ["Tech", "Energy"]


# ---------------------------------------------------------------------------
# ias_monitor
# ---------------------------------------------------------------------------

def test_tier34_coverage_finds_matching_articles(tmp_path):
    db = _make_ns_db(tmp_path, [
        {"uid": "a1", "title": "Ajinomoto raises ABF substrate prices",
         "url": "https://x.com/1", "source": "Bloomberg", "first_seen": _recent()},
        {"uid": "a2", "title": "Federal Reserve holds rates",
         "url": "https://x.com/2", "source": "Reuters", "first_seen": _recent()},
    ])
    hyp = _hyp(keywords=["ABF", "Ajinomoto"])
    hits = check_tier34_coverage([hyp], db_path=db, lookback_hours=24)
    assert len(hits) == 1
    _, articles = hits[0]
    assert len(articles) == 1
    assert articles[0]["source"] == "Bloomberg"


def test_lookback_window_excludes_old_articles(tmp_path):
    """Articles older than lookback_hours must not appear in results."""
    db = _make_ns_db(tmp_path, [
        {"uid": "old", "title": "ABF substrate warning",
         "url": "https://x.com/1", "source": "Bloomberg", "first_seen": _old()},
        {"uid": "new", "title": "ABF substrate warning",
         "url": "https://x.com/2", "source": "Reuters", "first_seen": _recent()},
    ])
    hyp = _hyp(keywords=["ABF"])
    hits = check_tier34_coverage([hyp], db_path=db, lookback_hours=24)
    assert len(hits) == 1
    _, articles = hits[0]
    assert len(articles) == 1
    assert articles[0]["uid"] == "new"


def test_tier34_coverage_no_false_positives(tmp_path):
    db = _make_ns_db(tmp_path, [
        {"uid": "a1", "title": "Fed raises interest rates again",
         "url": "https://x.com/1", "source": "Reuters", "first_seen": _recent()},
    ])
    hits = check_tier34_coverage([_hyp(keywords=["ABF", "Ajinomoto"])], db_path=db)
    assert hits == []


def test_should_alert_when_new_layer(tmp_path):
    hyp = _hyp(awareness_layer=2, alerted_layers=[])
    assert should_alert(hyp, []) is True


def test_should_not_alert_if_already_alerted(tmp_path):
    hyp = _hyp(awareness_layer=2, alerted_layers=[4])
    assert should_alert(hyp, []) is False


def test_should_not_alert_if_already_at_tier4():
    """Hypothesis already at awareness_layer=4 — no progression to report."""
    hyp = _hyp(awareness_layer=4, alerted_layers=[])
    assert should_alert(hyp, []) is False


def test_should_alert_when_hypothesis_at_tier3():
    """Layer 3 → Tier 4 coverage IS a new progression."""
    hyp = _hyp(awareness_layer=3, alerted_layers=[])
    assert should_alert(hyp, []) is True


def test_format_alert_contains_key_info():
    hyp = _hyp()
    articles = [{"source": "Bloomberg", "title": "ABF substrate supply crunch",
                 "url": "https://x.com/1", "sentiment_score": -0.4, "first_seen": "2026-06-15"}]
    alert = format_ias_alert(hyp, articles)
    assert "BN-2024-047" in alert
    assert "Bloomberg" in alert
    assert "8.7" in alert


def test_format_alert_truncates_at_three_articles():
    hyp = _hyp()
    articles = [
        {"source": f"Source{i}", "title": f"ABF news {i}",
         "url": f"https://x.com/{i}", "sentiment_score": -0.5, "first_seen": "2026-06-15"}
        for i in range(5)
    ]
    alert = format_ias_alert(hyp, articles)
    assert "...and 2 more" in alert


def test_run_check_calls_send_fn(tmp_path):
    db = _make_ns_db(tmp_path, [
        {"uid": "a1", "title": "Ajinomoto ABF substrate supply warning",
         "url": "https://x.com/1", "source": "Bloomberg", "first_seen": _recent()},
    ])
    tracking = tmp_path / "tracking.db"
    hyp = _hyp(awareness_layer=2)
    sent = []
    alerted = run_check([hyp], send_alert_fn=sent.append, db_path=db,
                        tracking_db_path=tracking, lookback_hours=24)
    assert alerted == ["BN-2024-047"]
    assert len(sent) == 1
    assert "BN-2024-047" in sent[0]


def test_run_check_persists_and_deduplicates(tmp_path):
    """Second run_check call must not re-alert for the same hypothesis."""
    db = _make_ns_db(tmp_path, [
        {"uid": "a1", "title": "ABF substrate supply news",
         "url": "https://x.com/1", "source": "Reuters", "first_seen": _recent()},
    ])
    tracking = tmp_path / "tracking.db"
    hyp1 = _hyp(awareness_layer=2)
    sent = []
    run_check([hyp1], send_alert_fn=sent.append, db_path=db,
              tracking_db_path=tracking, lookback_hours=24)
    assert len(sent) == 1

    # Second run — same DB, same hypothesis — should NOT alert again
    hyp2 = _hyp(awareness_layer=2)  # fresh object, no in-memory state
    run_check([hyp2], send_alert_fn=sent.append, db_path=db,
              tracking_db_path=tracking, lookback_hours=24)
    assert len(sent) == 1  # still 1 — no duplicate alert


def test_persist_and_load_alerted_layers(tmp_path):
    tracking = tmp_path / "tracking.db"
    assert load_alerted_layers("BN-2024-047", tracking) == []
    persist_alert("BN-2024-047", 4, tracking)
    assert load_alerted_layers("BN-2024-047", tracking) == [4]


# ---------------------------------------------------------------------------
# topic_sync
# ---------------------------------------------------------------------------

def test_sync_adds_bde_topics(tmp_path):
    config = tmp_path / "settings.yaml"
    sync_tier1_hypotheses([
        {"id": "BN-2024-047", "statement": "ABF substrate...", "keywords": ["ABF", "Ajinomoto"]},
        {"id": "BN-2024-051", "statement": "CoWoS capacity...", "keywords": ["CoWoS", "TSMC"]},
    ], config_path=config)
    topics = list_bde_topics(config_path=config)
    assert len(topics) == 2
    assert any(t["name"] == "BDE BN-2024-047" for t in topics)


def test_sync_preserves_manual_topics(tmp_path):
    import yaml
    config = tmp_path / "settings.yaml"
    config.write_text(yaml.dump({
        "topics": [{"name": "My Portfolio", "keywords": ["nvidia", "apple"]}]
    }))
    sync_tier1_hypotheses(
        [{"id": "BN-2024-047", "statement": "ABF...", "keywords": ["ABF"]}],
        config_path=config,
    )
    data = yaml.safe_load(config.read_text())
    names = [t["name"] for t in data["topics"]]
    assert "My Portfolio" in names
    assert "BDE BN-2024-047" in names


def test_sync_replaces_old_bde_topics(tmp_path):
    config = tmp_path / "settings.yaml"
    sync_tier1_hypotheses(
        [{"id": "BN-OLD", "statement": "old...", "keywords": ["old"]}],
        config_path=config,
    )
    sync_tier1_hypotheses(
        [{"id": "BN-NEW", "statement": "new...", "keywords": ["new"]}],
        config_path=config,
    )
    names = [t["name"] for t in list_bde_topics(config_path=config)]
    assert "BDE BN-NEW" in names
    assert "BDE BN-OLD" not in names


def test_sync_write_is_atomic(tmp_path):
    """Even if we can't easily simulate a crash, verify the file is valid YAML after write."""
    import yaml
    config = tmp_path / "settings.yaml"
    sync_tier1_hypotheses(
        [{"id": "BN-2024-047", "statement": "ABF...", "keywords": ["ABF"]}],
        config_path=config,
    )
    # File must be readable and valid YAML
    data = yaml.safe_load(config.read_text())
    assert "topics" in data


def test_remove_hypothesis(tmp_path):
    config = tmp_path / "settings.yaml"
    sync_tier1_hypotheses(
        [{"id": "BN-2024-047", "statement": "ABF...", "keywords": ["ABF"]}],
        config_path=config,
    )
    assert remove_hypothesis("BN-2024-047", config_path=config) is True
    assert list_bde_topics(config_path=config) == []


def test_remove_nonexistent_hypothesis(tmp_path):
    config = tmp_path / "settings.yaml"
    assert remove_hypothesis("BN-DOES-NOT-EXIST", config_path=config) is False
