"""Celery tasks for Phase 6 ACH contrarian engine."""
from celery import shared_task
from loguru import logger


@shared_task(bind=True, max_retries=1, default_retry_delay=300,
             name="contrarian.celery_tasks.run_ach_review")
def run_ach_review(self) -> dict:
    try:
        from contrarian.ach_engine import run
        result = run()
        logger.info(f"[Celery] ACH review: {result}")
        return result
    except Exception as exc:
        logger.exception(f"[Celery] ACH review failed: {exc}")
        raise self.retry(exc=exc)
