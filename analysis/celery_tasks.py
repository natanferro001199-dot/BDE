"""Celery tasks for Phase 4 structural analysis."""
from celery import shared_task
from loguru import logger


@shared_task(bind=True, max_retries=1, default_retry_delay=300,
             name="analysis.structural_analyzer.run")
def run_structural_analysis(self) -> dict:
    try:
        from analysis.structural_analyzer import run
        result = run()
        logger.info(f"[Celery] Structural analysis: {result['nodes_analyzed']} nodes, "
                    f"{result['articulation_points']} APs")
        return {
            "nodes_analyzed": result["nodes_analyzed"],
            "edges_analyzed": result["edges_analyzed"],
            "articulation_points": result["articulation_points"],
            "run_at": result["run_at"],
        }
    except Exception as exc:
        logger.exception(f"[Celery] Structural analysis failed: {exc}")
        raise self.retry(exc=exc)
