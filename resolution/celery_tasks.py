"""Celery tasks for Phase 3 entity resolution."""
from celery import shared_task
from loguru import logger


@shared_task(bind=True, max_retries=2, default_retry_delay=60,
             name="resolution.celery_tasks.run_resolver")
def run_resolver(self, batch_size: int = 20) -> dict:
    try:
        from resolution.resolver import resolve_batch
        result = resolve_batch(batch_size=batch_size)
        logger.info(f"[Celery] Entity resolver: {result}")
        return result
    except Exception as exc:
        logger.warning(f"[Celery] Entity resolver failed: {exc}")
        raise self.retry(exc=exc)
