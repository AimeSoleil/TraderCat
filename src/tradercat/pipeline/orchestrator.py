"""Pipeline orchestrator V2 - 3-phase queue pipeline.

Phase 1 (Q1): Signal generation for all unique symbols (global + watchlist).
Phase 2 (Q2): Global reports - macro summary + batched execution plans.
Phase 3 (Q3): User reports - personalized briefings per user with preferred persona.

Each phase waits for the previous to complete (barrier pattern).
"""
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
    GlobalReport,
    UserReport,
    User,
    WatchlistItem,
)
from tradercat.pipeline.signal_worker import process_symbols_q1
from tradercat.pipeline.report_worker import generate_global_reports_q2
from tradercat.pipeline.user_report_worker import generate_user_reports_q3
from tradercat.pipeline.holidays import is_market_day

logger = get_logger(__name__)


class PipelineOrchestrator:
    """Orchestrates the V2 3-phase pipeline execution."""
    
    def __init__(self):
        self.global_symbols = settings.global_symbols
        self.max_concurrency = settings.pipeline_max_concurrency
        self.batch_size = settings.pipeline_report_batch_size
    
    async def run_pipeline(self, run_date: date | None = None) -> bool:
        """
        Run the complete V2 pipeline for the given date.
        
        Flow: Q1 (signals) → Q2 (global reports) → Q3 (user reports)
        """
        run_date = run_date or datetime.utcnow().date()
        
        if not is_market_day(run_date):
            logger.info(f"Skipping pipeline for {run_date} - not a market day")
            return False
        
        async with AsyncSessionLocal() as db:
            try:
                # Check / create pipeline run
                pipeline_run = await self._get_or_create_pipeline_run(db, run_date)
                if pipeline_run is None:
                    return False
                
                # Start pipeline
                pipeline_run.status = PipelineStatus.RUNNING.value
                pipeline_run.started_at = datetime.utcnow()
                await db.commit()
                
                # Execute 3-phase pipeline
                success = await self._execute_v2_pipeline(db, pipeline_run)
                
                # Finalize
                pipeline_run.status = PipelineStatus.COMPLETED.value if success else PipelineStatus.FAILED.value
                pipeline_run.completed_at = datetime.utcnow()
                await db.commit()
                
                return success
                
            except Exception as e:
                logger.error(f"Pipeline failed: {e}", exc_info=True)
                if pipeline_run:
                    pipeline_run.status = PipelineStatus.FAILED.value
                    pipeline_run.error_log = str(e)
                    await db.commit()
                return False
    
    async def _get_or_create_pipeline_run(
        self, db: AsyncSession, run_date: date
    ) -> PipelineRun | None:
        """Get existing or create new pipeline run."""
        result = await db.execute(
            select(PipelineRun).where(PipelineRun.run_date == run_date)
        )
        pipeline_run = result.scalars().first()
        
        if pipeline_run:
            if pipeline_run.status == PipelineStatus.COMPLETED.value:
                logger.info(f"Pipeline already completed for {run_date}")
                return None
            elif pipeline_run.status == PipelineStatus.RUNNING.value:
                logger.warning(f"Pipeline already running for {run_date}")
                return None
        else:
            from uuid import uuid4
            pipeline_run = PipelineRun(
                id=uuid4(),
                run_date=run_date,
                status=PipelineStatus.PENDING.value,
            )
            db.add(pipeline_run)
            await db.commit()
            await db.refresh(pipeline_run)
        
        return pipeline_run
    
    async def _execute_v2_pipeline(
        self, db: AsyncSession, pipeline_run: PipelineRun
    ) -> bool:
        """Execute the 3-phase V2 pipeline."""
        try:
            # =============================================
            # PHASE 1 (Q1): Signal Generation
            # =============================================
            logger.info("=" * 60)
            logger.info("PHASE 1 (Q1): Signal Generation")
            logger.info("=" * 60)
            pipeline_run.step = "q1_signals"
            await db.commit()
            
            # Collect all unique symbols: global + all watchlists
            result = await db.execute(select(WatchlistItem.symbol).distinct())
            watchlist_symbols = [row[0] for row in result.all()]
            
            all_symbols = list(dict.fromkeys(
                self.global_symbols + watchlist_symbols
            ))  # Preserves order, deduplicates
            
            pipeline_run.total_symbols = len(all_symbols)
            await db.commit()
            
            logger.info(f"Q1: Processing {len(all_symbols)} unique symbols "
                        f"({len(self.global_symbols)} global + "
                        f"{len(watchlist_symbols)} watchlist, deduped)")
            
            all_signals = await process_symbols_q1(
                symbols=all_symbols,
                run_date=pipeline_run.run_date,
                pipeline_run_id=pipeline_run.id,
                max_concurrency=self.max_concurrency,
            )
            
            # Save signals to DB
            for signal_data in all_signals:
                db.add(SignalRecord(**signal_data))
            
            pipeline_run.processed_symbols = len(all_symbols)
            await db.commit()
            logger.info(f"Q1 DONE: {len(all_signals)} signals saved")
            
            # =============================================
            # PHASE 2 (Q2): Global Reports
            # =============================================
            logger.info("=" * 60)
            logger.info("PHASE 2 (Q2): Global Reports")
            logger.info("=" * 60)
            pipeline_run.step = "q2_global_reports"
            await db.commit()
            
            global_report_records = await generate_global_reports_q2(
                run_date=pipeline_run.run_date,
                all_signals=all_signals,
                pipeline_run_id=pipeline_run.id,
                global_symbols=self.global_symbols,
                batch_size=self.batch_size,
                max_concurrency=self.max_concurrency,
            )
            
            # Save global reports to DB
            for report_data in global_report_records:
                db.add(GlobalReport(**report_data))
            await db.commit()
            
            # Build lookup for Q3
            summary_report_md = ""
            symbol_plans: Dict[str, str] = {}
            for rec in global_report_records:
                if rec["report_type"] == "macro_summary":
                    summary_report_md = rec["content_md"]
                elif rec["report_type"] == "symbol_execution_plan" and rec.get("symbol"):
                    symbol_plans[rec["symbol"]] = rec["content_md"]
            
            logger.info(f"Q2 DONE: 1 summary + {len(symbol_plans)} execution plans saved")
            
            # =============================================
            # PHASE 3 (Q3): User Reports
            # =============================================
            logger.info("=" * 60)
            logger.info("PHASE 3 (Q3): User Reports")
            logger.info("=" * 60)
            pipeline_run.step = "q3_user_reports"
            await db.commit()
            
            # Get all active users with their watchlists
            result = await db.execute(
                select(User).where(User.is_active == True)
            )
            active_users = result.scalars().all()
            
            user_tasks = []
            for user in active_users:
                # Get user's watchlist symbols
                result = await db.execute(
                    select(WatchlistItem.symbol).where(
                        WatchlistItem.user_id == user.id
                    )
                )
                user_symbols = [row[0] for row in result.all()]
                
                if not user_symbols:
                    logger.info(f"Q3: Skipping user {user.username} - empty watchlist")
                    continue
                
                # Filter symbol plans to user's watchlist
                user_symbol_plans = {
                    sym: symbol_plans[sym]
                    for sym in user_symbols
                    if sym in symbol_plans
                }
                
                # Resolve persona: user preference > default
                persona = user.preferred_persona or settings.default_persona
                lang = user.preferred_lang
                
                user_tasks.append({
                    "user_id": user.id,
                    "run_date": pipeline_run.run_date,
                    "summary_report_md": summary_report_md,
                    "symbol_plans": user_symbol_plans,
                    "persona": persona,
                    "lang": lang,
                    "pipeline_run_id": pipeline_run.id,
                })
            
            pipeline_run.total_reports = len(user_tasks)
            await db.commit()
            logger.info(f"Q3: Generating reports for {len(user_tasks)} users")
            
            if user_tasks:
                user_report_records = await generate_user_reports_q3(
                    user_tasks=user_tasks,
                    max_concurrency=self.max_concurrency,
                )
                
                for report_data in user_report_records:
                    db.add(UserReport(**report_data))
                
                pipeline_run.processed_reports = len(user_report_records)
                await db.commit()
                logger.info(f"Q3 DONE: {len(user_report_records)} user reports saved")
            
            # =============================================
            # COMPLETE
            # =============================================
            pipeline_run.step = "completed"
            await db.commit()
            
            logger.info("=" * 60)
            logger.info("PIPELINE V2 COMPLETE")
            logger.info(f"  Signals: {len(all_signals)}")
            logger.info(f"  Global reports: {len(global_report_records)}")
            logger.info(f"  User reports: {pipeline_run.processed_reports}")
            logger.info("=" * 60)
            
            return True
            
        except Exception as e:
            logger.error(f"Pipeline step '{pipeline_run.step}' failed: {e}", exc_info=True)
            pipeline_run.error_log = f"[{pipeline_run.step}] {str(e)}"
            await db.commit()
            return False
