"""Pipeline orchestrator - coordinates nightly signal and report generation."""
import asyncio
from datetime import datetime, date, timedelta
from typing import List, Dict, Any
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tradercat.logger.logger import get_logger
from tradercat.config import settings
from tradercat.database import AsyncSessionLocal
from tradercat.models import (
    PipelineRun,
    PipelineStatus,
    SignalRecord,
    SignalScope,
    User,
    WatchlistItem,
    Report,
)
from tradercat.pipeline.signal_worker import process_symbols_concurrent
from tradercat.pipeline.report_worker import generate_reports_concurrent
from tradercat.pipeline.holidays import is_market_day

logger = get_logger(__name__)


class PipelineOrchestrator:
    """Orchestrates the nightly pipeline execution."""
    
    def __init__(self):
        """Initialize pipeline orchestrator."""
        self.global_symbols = settings.global_symbols
        self.max_concurrency = settings.pipeline_max_concurrency
    
    async def run_pipeline(self, run_date: date | None = None) -> bool:
        """
        Run the complete pipeline for the given date.
        
        Args:
            run_date: Date to run pipeline for (defaults to today)
            
        Returns:
            True if successful, False otherwise
        """
        run_date = run_date or datetime.now(datetime.timezone.utc).date()
        
        # Check if it's a market day
        if not is_market_day(run_date):
            logger.info(f"Skipping pipeline for {run_date} - not a market day")
            return False
        
        async with AsyncSessionLocal() as db:
            try:
                # Check for existing pipeline run
                result = await db.execute(
                    select(PipelineRun).where(PipelineRun.run_date == run_date)
                )
                pipeline_run = result.scalars().first()
                
                if pipeline_run:
                    if pipeline_run.status == PipelineStatus.COMPLETED:
                        logger.info(f"Pipeline already completed for {run_date}")
                        return True
                    elif pipeline_run.status == PipelineStatus.RUNNING:
                        logger.warning(f"Pipeline already running for {run_date}")
                        return False
                else:
                    # Create new pipeline run
                    from uuid import uuid4
                    pipeline_run = PipelineRun(
                        id=uuid4(),
                        run_date=run_date,
                        status=PipelineStatus.PENDING,
                    )
                    db.add(pipeline_run)
                    await db.commit()
                    await db.refresh(pipeline_run)
                
                # Start pipeline
                pipeline_run.status = PipelineStatus.RUNNING
                pipeline_run.started_at = datetime.now(datetime.timezone.utc)
                await db.commit()
                
                # Execute pipeline steps
                success = await self._execute_pipeline_steps(db, pipeline_run)
                
                # Update final status
                if success:
                    pipeline_run.status = PipelineStatus.COMPLETED
                    pipeline_run.completed_at = datetime.now(datetime.timezone.utc)
                else:
                    pipeline_run.status = PipelineStatus.FAILED
                
                await db.commit()
                return success
                
            except Exception as e:
                logger.error(f"Pipeline failed: {e}", exc_info=True)
                if pipeline_run:
                    pipeline_run.status = PipelineStatus.FAILED
                    pipeline_run.error_log = str(e)
                    await db.commit()
                return False
    
    async def _execute_pipeline_steps(
        self,
        db: AsyncSession,
        pipeline_run: PipelineRun
    ) -> bool:
        """Execute all pipeline steps."""
        try:
            # Step 1: Global Signal Generation
            logger.info("Step 1: Generating global signals...")
            pipeline_run.step = "global_signals"
            pipeline_run.total_symbols = len(self.global_symbols)
            await db.commit()
            
            global_signals = await process_symbols_concurrent(
                symbols=self.global_symbols,
                run_date=pipeline_run.run_date,
                scope=SignalScope.GLOBAL,
                pipeline_run_id=pipeline_run.id,
                max_concurrency=self.max_concurrency
            )
            
            # Save global signals
            for signal_data in global_signals:
                signal = SignalRecord(**signal_data)
                db.add(signal)
            
            pipeline_run.processed_symbols = len(self.global_symbols)
            await db.commit()
            logger.info(f"Generated {len(global_signals)} global signals")
            
            # Step 2: User-Space Signal Generation (Deduplicated)
            logger.info("Step 2: Generating user-space signals...")
            pipeline_run.step = "user_signals"
            await db.commit()
            
            # Get all unique watchlist symbols (excluding global symbols)
            result = await db.execute(
                select(WatchlistItem.symbol).distinct()
            )
            all_watchlist_symbols = [row[0] for row in result.all()]
            user_symbols = [s for s in all_watchlist_symbols if s not in self.global_symbols]
            
            logger.info(f"Processing {len(user_symbols)} unique user symbols")
            pipeline_run.total_symbols += len(user_symbols)
            await db.commit()
            
            if user_symbols:
                user_signals = await process_symbols_concurrent(
                    symbols=user_symbols,
                    run_date=pipeline_run.run_date,
                    scope=SignalScope.USER,
                    pipeline_run_id=pipeline_run.id,
                    max_concurrency=self.max_concurrency
                )
                
                # Save user signals
                for signal_data in user_signals:
                    signal = SignalRecord(**signal_data)
                    db.add(signal)
                
                pipeline_run.processed_symbols += len(user_symbols)
                await db.commit()
                logger.info(f"Generated {len(user_signals)} user-space signals")
            
            # Step 3: LLM Report Generation
            logger.info("Step 3: Generating LLM reports...")
            pipeline_run.step = "reports"
            await db.commit()
            
            # Get all active users
            result = await db.execute(
                select(User).where(User.is_active == True)
            )
            active_users = result.scalars().all()
            
            # Build report tasks
            report_tasks = []
            for user in active_users:
                # Get user's watchlist
                result = await db.execute(
                    select(WatchlistItem).where(WatchlistItem.user_id == user.id)
                )
                watchlist_items = result.scalars().all()
                
                for item in watchlist_items:
                    # Prepare signal context for this symbol
                    signal_context = await self._build_signal_context(
                        db, item.symbol, pipeline_run.run_date
                    )
                    
                    report_tasks.append({
                        "user_id": user.id,
                        "symbol": item.symbol,
                        "run_date": pipeline_run.run_date,
                        "signal_context": signal_context,
                        "pipeline_run_id": pipeline_run.id,
                    })
            
            pipeline_run.total_reports = len(report_tasks)
            await db.commit()
            logger.info(f"Generating {len(report_tasks)} reports")
            
            if report_tasks:
                report_records = await generate_reports_concurrent(
                    report_tasks=report_tasks,
                    max_concurrency=self.max_concurrency
                )
                
                # Save reports
                for report_data in report_records:
                    report = Report(**report_data)
                    db.add(report)
                
                pipeline_run.processed_reports = len(report_records)
                await db.commit()
                logger.info(f"Generated {len(report_records)} reports")
            
            # Step 4: Complete
            logger.info("Pipeline completed successfully")
            pipeline_run.step = "completed"
            await db.commit()
            
            return True
            
        except Exception as e:
            logger.error(f"Pipeline step failed: {e}", exc_info=True)
            return False
    
    async def _build_signal_context(
        self,
        db: AsyncSession,
        symbol: str,
        run_date: date
    ) -> Dict[str, Any]:
        """
        Build signal context for LLM report generation.
        Includes today's signals, past 3 days, and global signals.
        """
        # Today's signals for this symbol
        result = await db.execute(
            select(SignalRecord).where(
                SignalRecord.run_date == run_date,
                SignalRecord.symbol == symbol
            )
        )
        today_signals = [
            {
                "strategy": s.strategy,
                "signal": s.signal,
                "confidence": s.confidence,
                "reason": s.reason,
            }
            for s in result.scalars().all()
        ]
        
        # Past 3 days signals
        past_dates = [run_date - timedelta(days=i) for i in range(1, 4)]
        result = await db.execute(
            select(SignalRecord).where(
                SignalRecord.run_date.in_(past_dates),
                SignalRecord.symbol == symbol
            )
        )
        past_signals = [
            {
                "date": str(s.run_date),
                "strategy": s.strategy,
                "signal": s.signal,
                "confidence": s.confidence,
            }
            for s in result.scalars().all()
        ]
        
        # Global signals for today
        result = await db.execute(
            select(SignalRecord).where(
                SignalRecord.run_date == run_date,
                SignalRecord.scope == SignalScope.GLOBAL
            ).limit(20)
        )
        global_signals = [
            {
                "symbol": s.symbol,
                "strategy": s.strategy,
                "signal": s.signal,
            }
            for s in result.scalars().all()
        ]
        
        return {
            "run_date": str(run_date),
            "today_signals": today_signals,
            "past_3d_signals": past_signals,
            "global_signals": global_signals,
        }
