"""Standalone pipeline runner for dedicated pipeline worker service.

This is the entry point for the pipeline worker service that runs
the scheduler independently from the API service.

Usage:
    python -m tradercat.pipeline.runner

Environment:
    RUN_MODE=scheduler (required)

Docker:
    See Dockerfile.pipeline for containerized deployment

Architecture:
    API Service (main.py)           Pipeline Worker (this file)
    ├── FastAPI app                 ├── Scheduler loop
    ├── REST endpoints              ├── Signal generation
    ├── Manual triggers             ├── Report generation
    └── No scheduler code           └── APScheduler cron

The API and pipeline services are completely separated:
- API: Never imports scheduler module when RUN_MODE=api-only
- Pipeline: Only runs scheduler, no API endpoints
- Communication: Via shared PostgreSQL database
"""
import asyncio
import signal
import sys
from datetime import datetime

import logging

from tradercat.logger.logger import get_logger
from tradercat.config import settings
from tradercat.pipeline.scheduler import get_scheduler

# Set up logger
use_json = settings.log_format == "json"
logger = get_logger(__name__, level=getattr(logging, settings.log_level), use_json=use_json)

# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    sig_name = signal.Signals(signum).name
    logger.info(f"Received {sig_name} signal, initiating graceful shutdown...")
    shutdown_requested = True


async def run_pipeline_worker():
    """
    Main entry point for standalone pipeline worker.
    Runs the scheduler and keeps the process alive.
    """
    logger.info("=" * 80)
    logger.info("TraderCat Pipeline Worker Starting")
    logger.info(f"Mode: {settings.run_mode}")
    logger.info(f"Schedule: {settings.pipeline_schedule_hour}:00 {settings.pipeline_timezone}")
    logger.info("=" * 80)
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start the scheduler
        scheduler = get_scheduler()
        scheduler.start()
        
        next_run = scheduler.get_next_run_time()
        if next_run:
            logger.info(f"Next scheduled run: {next_run}")
        
        # Keep the worker alive until shutdown is requested
        logger.info("Pipeline worker is running. Press Ctrl+C to stop.")
        
        while not shutdown_requested:
            await asyncio.sleep(1)
        
        # Graceful shutdown
        logger.info("Shutting down pipeline worker...")
        from tradercat.pipeline.scheduler import stop_scheduler
        stop_scheduler()
        logger.info("Pipeline worker stopped successfully")
        
        return 0
        
    except Exception as e:
        logger.error(f"Fatal error in pipeline worker: {e}", exc_info=True)
        return 1


def main():
    """Main entry point for the pipeline worker."""
    # Validate run mode
    if settings.run_mode not in ["scheduler", "combined"]:
        logger.error(
            f"Invalid RUN_MODE '{settings.run_mode}' for pipeline worker. "
            "Expected 'scheduler' or 'combined'"
        )
        sys.exit(1)
    
    # Run the async worker
    try:
        exit_code = asyncio.run(run_pipeline_worker())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Pipeline worker interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
