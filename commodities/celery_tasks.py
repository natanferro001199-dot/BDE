"""
celery_tasks.py — Daily commodity shortage analysis via 5-agent Mistral debate.

Scheduled at 06:30 UTC every day in celery_app.py.
Target completion: 18-25 minutes for all 35 commodities.
"""
from __future__ import annotations

from celery import shared_task
from loguru import logger


@shared_task(
    bind=True,
    max_retries=1,
    default_retry_delay=600,
    soft_time_limit=2400,
    time_limit=2700,
    name="commodities.celery_tasks.run_daily_analysis",
)
def run_daily_analysis(self) -> dict:
    try:
        from commodities.analyst import run_all
        result = run_all()
        logger.info(f"[Celery:commodities] {result}")
        return result
    except Exception as exc:
        logger.exception(f"[Celery:commodities] Analysis failed: {exc}")
        raise self.retry(exc=exc)
