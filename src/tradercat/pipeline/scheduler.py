"""Pipeline scheduler using APScheduler.

IMPORTANT: This module should ONLY be used by:
1. The standalone pipeline worker (tradercat.pipeline.runner)
2. Legacy combined mode (not recommended for production)

For production deployments:
- API Service: Use RUN_MODE=api-only (no scheduler imports)
- Pipeline Worker: Use RUN_MODE=scheduler (runs this scheduler)

Manual pipeline triggers from the API use PipelineOrchestrator directly,
not the scheduler.
"""
import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import logging

from tradercat.logger.logger import get_logger
from tradercat.config import settings
from tradercat.pipeline.orchestrator import PipelineOrchestrator
from tradercat.pipeline.holidays import is_market_day

# Set up logger
use_json = settings.log_format == "json"
logger = get_logger(__name__, level=getattr(logging, settings.log_level), use_json=use_json)


class PipelineScheduler:
    """Scheduler for nightly pipeline execution."""
    
    def __init__(self):
        """Initialize pipeline scheduler."""
        self.scheduler = AsyncIOScheduler()
        self.orchestrator = PipelineOrchestrator()
        self.timezone = pytz.timezone(settings.pipeline_timezone)
    
    async def run_scheduled_pipeline(self):
        """
        Scheduled pipeline job.
        Checks if today is a market day before running.
        """
        today = datetime.now(self.timezone).date()
        
        logger.info(f"Scheduled pipeline triggered for {today}")
        
        if not is_market_day(today):
            logger.info(f"Skipping pipeline - {today} is not a market day")
            return
        
        try:
            success = await self.orchestrator.run_pipeline(today)
            if success:
                logger.info("Scheduled pipeline completed successfully")
            else:
                logger.error("Scheduled pipeline failed")
        except Exception as e:
            logger.error(f"Scheduled pipeline error: {e}", exc_info=True)
    
    def start(self):
        """Start the scheduler."""
        # Schedule pipeline to run at configured hour (8 PM ET by default)
        trigger = CronTrigger(
            hour=settings.pipeline_schedule_hour,
            minute=0,
            timezone=self.timezone
        )
        
        self.scheduler.add_job(
            self.run_scheduled_pipeline,
            trigger=trigger,
            id="nightly_pipeline",
            name="Nightly Signal & Report Generation",
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info(f"Pipeline scheduler started - will run at {settings.pipeline_schedule_hour}:00 {settings.pipeline_timezone}")
    
    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown(wait=True)
        logger.info("Pipeline scheduler stopped")
    
    def get_next_run_time(self) -> datetime | None:
        """Get the next scheduled run time."""
        job = self.scheduler.get_job("nightly_pipeline")
        if job:
            return job.next_run_time
        return None


# Global scheduler instance
_scheduler: PipelineScheduler | None = None


def get_scheduler() -> PipelineScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = PipelineScheduler()
    return _scheduler


def start_scheduler():
    """Start the global scheduler."""
    scheduler = get_scheduler()
    scheduler.start()


def stop_scheduler():
    """Stop the global scheduler."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.stop()
        _scheduler = None
