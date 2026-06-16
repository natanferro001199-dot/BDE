"""
Celery tasks for Phase 2 ingestion pipeline.

Each task wraps an ingestor's run() function so it can be scheduled by Celery beat
and retried on transient network failures.
"""
from celery import shared_task
from loguru import logger


@shared_task(bind=True, max_retries=3, default_retry_delay=120, name="ingestion.celery_tasks.run_github")
def run_github(self, lookback_hours: int = 96) -> dict:
    try:
        from ingestion.github_ingestor import run
        result = run(lookback_hours=lookback_hours)
        logger.info(f"[Celery] GitHub ingestor: {result}")
        return result
    except Exception as exc:
        logger.warning(f"[Celery] GitHub ingestor failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=120, name="ingestion.celery_tasks.run_hn")
def run_hn(self, lookback_hours: int = 48) -> dict:
    try:
        from ingestion.hn_ingestor import run
        result = run(lookback_hours=lookback_hours)
        logger.info(f"[Celery] HN ingestor: {result}")
        return result
    except Exception as exc:
        logger.warning(f"[Celery] HN ingestor failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=300, name="ingestion.celery_tasks.run_edgar")
def run_edgar(self, days_back: int = 30) -> dict:
    try:
        from ingestion.edgar_ingestor import run
        result = run(days_back=days_back)
        logger.info(f"[Celery] EDGAR ingestor: {result}")
        return result
    except Exception as exc:
        logger.warning(f"[Celery] EDGAR ingestor failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=300, name="ingestion.celery_tasks.run_arxiv")
def run_arxiv(self, days_back: int = 14) -> dict:
    try:
        from ingestion.arxiv_ingestor import run
        result = run(days_back=days_back)
        logger.info(f"[Celery] arXiv ingestor: {result}")
        return result
    except Exception as exc:
        logger.warning(f"[Celery] arXiv ingestor failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, name="ingestion.celery_tasks.run_rss")
def run_rss(self) -> dict:
    try:
        from ingestion.rss_ingestor import run
        result = run()
        logger.info(f"[Celery] RSS ingestor: {result}")
        return result
    except Exception as exc:
        logger.warning(f"[Celery] RSS ingestor failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=120, name="ingestion.celery_tasks.run_reddit")
def run_reddit(self, lookback_hours: int = 48) -> dict:
    try:
        from ingestion.reddit_ingestor import run
        result = run(lookback_hours=lookback_hours)
        logger.info(f"[Celery] Reddit ingestor: {result}")
        return result
    except Exception as exc:
        logger.warning(f"[Celery] Reddit ingestor failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=300, name="ingestion.celery_tasks.run_uspto")
def run_uspto(self, days_back: int = 90) -> dict:
    try:
        from ingestion.uspto_ingestor import run
        result = run(days_back=days_back)
        logger.info(f"[Celery] USPTO ingestor: {result}")
        return result
    except Exception as exc:
        logger.warning(f"[Celery] USPTO ingestor failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=120, name="ingestion.celery_tasks.run_jobs")
def run_jobs(self) -> dict:
    try:
        from ingestion.jobs_ingestor import run
        result = run()
        logger.info(f"[Celery] Jobs ingestor: {result}")
        return result
    except Exception as exc:
        logger.warning(f"[Celery] Jobs ingestor failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, name="ingestion.celery_tasks.process_documents")
def process_documents(self, batch_size: int = 50) -> dict:
    try:
        from processing.document_processor import process_batch
        result = process_batch(batch_size=batch_size)
        logger.info(f"[Celery] Document processor: {result}")
        return result
    except Exception as exc:
        logger.warning(f"[Celery] Document processor failed: {exc}")
        raise self.retry(exc=exc)
