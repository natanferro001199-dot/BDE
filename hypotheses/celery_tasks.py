"""Celery tasks for Phase 5 hypothesis engine."""
from celery import shared_task
from loguru import logger


@shared_task(bind=True, max_retries=1, default_retry_delay=300,
             name="hypotheses.celery_tasks.run_hypothesis_generator")
def run_hypothesis_generator(self, top_n: int = 10) -> dict:
    try:
        from hypotheses.hypothesis_generator import run
        result = run(top_n=top_n)
        logger.info(f"[Celery] Hypothesis generator: {result}")
        return result
    except Exception as exc:
        logger.exception(f"[Celery] Hypothesis generator failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=60,
             name="hypotheses.celery_tasks.check_ias_windows")
def check_ias_windows_task(self) -> dict:
    try:
        from hypotheses.evidence_updater import check_ias_windows
        windows = check_ias_windows()
        logger.info(f"[Celery] IAS windows check: {len(windows)} hypotheses at risk of going public")
        return {"ias_windows": len(windows), "ids": [h["id"] for h in windows]}
    except Exception as exc:
        logger.warning(f"[Celery] IAS check failed: {exc}")
        raise self.retry(exc=exc)
