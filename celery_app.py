from celery import Celery
from celery.schedules import crontab
from config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND

app = Celery("bde", broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

app.autodiscover_tasks(["ingestion", "processing", "resolution", "analysis", "hypotheses", "contrarian", "integration", "alerts", "commodities"])

app.conf.beat_schedule = {
    # Phase 2 — Ingestion (Tier 1-2 sources only; Tier 3-4 handled by news-sentiment)
    "ingest-github-every-4h": {
        "task": "ingestion.celery_tasks.run_github",
        "schedule": crontab(minute=0, hour="*/4"),
    },
    "ingest-hn-every-4h": {
        "task": "ingestion.celery_tasks.run_hn",
        "schedule": crontab(minute=30, hour="*/4"),
    },
    "ingest-rss-every-6h": {
        "task": "ingestion.celery_tasks.run_rss",
        "schedule": crontab(minute=0, hour="*/6"),
    },
    "ingest-edgar-daily": {
        "task": "ingestion.celery_tasks.run_edgar",
        "schedule": crontab(minute=0, hour=6),
    },
    "ingest-arxiv-daily": {
        "task": "ingestion.celery_tasks.run_arxiv",
        "schedule": crontab(minute=30, hour=6),
    },
    # Phase 8 — Source expansion (Reddit every 6h, USPTO weekly, jobs daily)
    "ingest-reddit-every-6h": {
        "task": "ingestion.celery_tasks.run_reddit",
        "schedule": crontab(minute=45, hour="*/6"),
    },
    "ingest-uspto-weekly": {
        "task": "ingestion.celery_tasks.run_uspto",
        "schedule": crontab(minute=0, hour=5, day_of_week=1),
    },
    "ingest-jobs-daily": {
        "task": "ingestion.celery_tasks.run_jobs",
        "schedule": crontab(minute=0, hour=7),
    },
    # Phase 2 — Processing queue (runs every 2h, after main ingest cycles)
    "process-documents-every-2h": {
        "task": "ingestion.celery_tasks.process_documents",
        "schedule": crontab(minute=45, hour="*/2"),
    },
    # Phase 3 — Entity resolution (runs every hour, drains the queue)
    "resolve-entities-every-hour": {
        "task": "resolution.celery_tasks.run_resolver",
        "schedule": crontab(minute=15),
        "kwargs": {"batch_size": 30},
    },
    # Phase 4 — Structural analysis (weekly, low priority)
    "structural-analysis-weekly": {
        "task": "analysis.structural_analyzer.run",
        "schedule": crontab(minute=0, hour=2, day_of_week=1),
    },
    # Phase 5 — Hypothesis engine (weekly, after structural analysis)
    "generate-hypotheses-weekly": {
        "task": "hypotheses.celery_tasks.run_hypothesis_generator",
        "schedule": crontab(minute=30, hour=2, day_of_week=1),
        "kwargs": {"top_n": 10},
    },
    # Evidence catch-up (every 2h — reconciles MENTIONS edges not yet in evidence)
    "evidence-update-every-2h": {
        "task": "hypotheses.celery_tasks.run_evidence_update",
        "schedule": crontab(minute=30, hour="*/2"),
    },
    "check-ias-windows-every-6h": {
        "task": "hypotheses.celery_tasks.check_ias_windows",
        "schedule": crontab(minute=30, hour="*/6"),
    },
    # Phase 6 — ACH review (weekly, after hypothesis generation)
    "ach-review-weekly": {
        "task": "contrarian.celery_tasks.run_ach_review",
        "schedule": crontab(minute=0, hour=4, day_of_week=1),
    },
    # Integration — BDE <-> news-sentiment bridge
    "ias-window-check-every-6h": {
        "task": "integration.celery_tasks.check_ias_windows",
        "schedule": crontab(minute=0, hour="*/6"),
    },
    "ingest-tier34-every-6h": {
        "task": "integration.celery_tasks.ingest_tier34_articles",
        "schedule": crontab(minute=30, hour="*/6"),
    },
    # Alerts — Telegram notifications
    "alerts-daily-digest-08h": {
        "task": "alerts.celery_tasks.send_daily_digest",
        "schedule": crontab(minute=0, hour=8),
    },
    "alerts-check-new-tier1-6h": {
        "task": "alerts.celery_tasks.check_new_tier1",
        "schedule": crontab(minute=15, hour="*/6"),
    },
    "alerts-check-ach-needed-4h": {
        "task": "alerts.celery_tasks.check_ach_needed",
        "schedule": crontab(minute=45, hour="*/4"),
    },
    # Commodity shortage intelligence (daily at 06:30 UTC, after EDGAR/arXiv ingest)
    "commodity-daily-analysis-0630": {
        "task": "commodities.celery_tasks.run_daily_analysis",
        "schedule": crontab(minute=30, hour=6),
    },
}
