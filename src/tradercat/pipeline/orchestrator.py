"""Pipeline orchestrator — 3-phase queue pipeline.

Phase 1 (Q1): Signal generation for all unique symbols (global + watchlist).
Phase 2 (Q2): Global reports - macro summary + batched execution plans.
Phase 3 (Q3): User reports - personalized briefings per user with preferred persona.

Each phase waits for the previous to complete (barrier pattern).
"""
import asyncio
from datetime import datetime, date, timedelta
from typing import List, Dict, Any
from uuid import UUID
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

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
    GlobalSymbol,
    Strategy,
    StrategyPreset,
)
from tradercat.pipeline.signal_worker import process_symbols_q1
from tradercat.pipeline.report_worker import generate_global_reports_q2
from tradercat.pipeline.user_report_worker import generate_user_reports_q3
from tradercat.pipeline.holidays import is_market_day

logger = get_logger(__name__)


class PipelineOrchestrator:
    """Orchestrates the 3-phase pipeline execution."""
    
    def __init__(self):
        self.max_concurrency = settings.pipeline_max_concurrency
        self.batch_size = settings.pipeline_report_batch_size
    
    async def run_pipeline(self, run_date: date | None = None) -> bool:
        """
        Run the complete pipeline for the given date.
        
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
                success = await self._execute_pipeline(db, pipeline_run)
                
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
    
    async def _execute_pipeline(
        self, db: AsyncSession, pipeline_run: PipelineRun
    ) -> bool:
        """Execute the 3-phase pipeline."""
        try:
            # =============================================
            # PHASE 1 (Q1): Signal Generation
            # =============================================
            logger.info("=" * 60)
            logger.info("PHASE 1 (Q1): Signal Generation")
            logger.info("=" * 60)
            pipeline_run.step = "q1_signals"
            await db.commit()
            
            # ── Load active strategies + presets from DB ──
            from sqlalchemy.orm import selectinload
            strat_result = await db.execute(
                select(Strategy)
                .where(Strategy.is_active == True)
                .options(selectinload(Strategy.active_preset))
            )
            db_strategies = strat_result.scalars().all()

            strategy_configs = None
            if db_strategies:
                strategy_configs = []
                for strat in db_strategies:
                    params = {}
                    if strat.active_preset:
                        params = strat.active_preset.parameters or {}
                    strategy_configs.append({
                        "name": strat.name,
                        "strategy_class": strat.strategy_class,
                        "parameters": params,
                    })
                logger.info(f"Q1: Loaded {len(strategy_configs)} active strategies from DB")
            else:
                logger.warning("Q1: No active strategies in DB — will use hardcoded fallback")

            # Collect global symbols from database
            result = await db.execute(
                select(GlobalSymbol.symbol).order_by(GlobalSymbol.symbol_type, GlobalSymbol.symbol)
            )
            global_symbols = [row[0] for row in result.all()]

            if not global_symbols:
                logger.warning("No global symbols configured in database — "
                               "falling back to config default")
                global_symbols = settings.global_symbols

            # Collect all unique symbols: global + all watchlists
            result = await db.execute(select(WatchlistItem.symbol).distinct())
            watchlist_symbols = [row[0] for row in result.all()]
            
            all_symbols = list(dict.fromkeys(
                global_symbols + watchlist_symbols
            ))  # Preserves order, deduplicates
            
            pipeline_run.total_symbols = len(all_symbols)
            await db.commit()
            
            logger.info(f"Q1: Processing {len(all_symbols)} unique symbols "
                        f"({len(global_symbols)} global + "
                        f"{len(watchlist_symbols)} watchlist, deduped)")
            
            all_signals = await process_symbols_q1(
                symbols=all_symbols,
                run_date=pipeline_run.run_date,
                pipeline_run_id=pipeline_run.id,
                max_concurrency=self.max_concurrency,
                strategy_configs=strategy_configs,
            )
            
            # Save signals to DB (upsert: on conflict update)
            for signal_data in all_signals:
                stmt = pg_insert(SignalRecord).values(**signal_data)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_signal_run_date_symbol_strategy",
                    set_={
                        "signal": stmt.excluded.signal,
                        "confidence": stmt.excluded.confidence,
                        "reason": stmt.excluded.reason,
                        "details": stmt.excluded.details,
                        "scope": stmt.excluded.scope,
                        "pipeline_run_id": stmt.excluded.pipeline_run_id,
                        "created_at": stmt.excluded.created_at,
                    },
                )
                await db.execute(stmt)
            
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
                global_symbols=global_symbols,
                batch_size=self.batch_size,
                max_concurrency=self.max_concurrency,
                identity_key=settings.default_identity,
            )
            
            # Save global reports to DB (upsert: on conflict update)
            for report_data in global_report_records:
                stmt = pg_insert(GlobalReport).values(**report_data)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[
                        GlobalReport.run_date,
                        GlobalReport.report_type,
                        text("COALESCE(symbol, '')"),
                    ],
                    set_={
                        "content_md": stmt.excluded.content_md,
                        "model_used": stmt.excluded.model_used,
                        "identity_used": stmt.excluded.identity_used,
                        "input_context": stmt.excluded.input_context,
                        "pipeline_run_id": stmt.excluded.pipeline_run_id,
                        "created_at": stmt.excluded.created_at,
                    },
                )
                await db.execute(stmt)
            await db.commit()
            
            # Build lookup for Q3
            summary_report_md = ""
            portfolio_summary_md = ""
            symbol_plans: Dict[str, str] = {}
            for rec in global_report_records:
                if rec["report_type"] == "macro_summary":
                    summary_report_md = rec["content_md"]
                elif rec["report_type"] == "portfolio_summary":
                    portfolio_summary_md = rec["content_md"]
                elif rec["report_type"] == "symbol_execution_plan" and rec.get("symbol"):
                    symbol_plans[rec["symbol"]] = rec["content_md"]
            
            logger.info(f"Q2 DONE: 1 summary + {len(symbol_plans)} execution plans + 1 portfolio summary saved")
            
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
                    stmt = pg_insert(UserReport).values(**report_data)
                    stmt = stmt.on_conflict_do_update(
                        constraint="uq_user_report_user_run_date_type",
                        set_={
                            "content_md": stmt.excluded.content_md,
                            "model_used": stmt.excluded.model_used,
                            "identity_used": stmt.excluded.identity_used,
                            "input_context": stmt.excluded.input_context,
                            "pipeline_run_id": stmt.excluded.pipeline_run_id,
                            "created_at": stmt.excluded.created_at,
                        },
                    )
                    await db.execute(stmt)
                
                pipeline_run.processed_reports = len(user_report_records)
                await db.commit()
                logger.info(f"Q3 DONE: {len(user_report_records)} user reports saved")
            
            # =============================================
            # COMPLETE
            # =============================================
            pipeline_run.step = "completed"
            await db.commit()
            
            logger.info("=" * 60)
            logger.info("PIPELINE COMPLETE")
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
