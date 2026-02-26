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
    LlmToken,
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
    
    async def run_pipeline(
        self, run_date: date | None = None, *, force: bool = False
    ) -> bool:
        """
        Run the complete pipeline for the given date.

        Args:
            run_date: Target date (defaults to today).
            force: When True, reset a previous COMPLETED / FAILED run to
                   PENDING so it can be re-executed.  Data produced by the
                   pipeline (signals, reports) is upserted, so stale rows
                   are overwritten automatically.

        Flow: Q1 (signals) → Q2 (global reports) → Q3 (user reports)
        """
        run_date = run_date or datetime.utcnow().date()
        
        if not is_market_day(run_date):
            logger.info(f"Skipping pipeline for {run_date} - not a market day")
            return False
        
        async with AsyncSessionLocal() as db:
            try:
                # Check / create pipeline run
                pipeline_run = await self._get_or_create_pipeline_run(
                    db, run_date, force=force
                )
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
        self, db: AsyncSession, run_date: date, *, force: bool = False
    ) -> PipelineRun | None:
        """Get existing or create new pipeline run.

        When *force* is ``True``, a COMPLETED or FAILED run is reset to
        PENDING so the pipeline can overwrite its output.  A RUNNING run
        is never reset — the caller should reject the request in that case.
        """
        result = await db.execute(
            select(PipelineRun).where(PipelineRun.run_date == run_date)
        )
        pipeline_run = result.scalars().first()

        if pipeline_run:
            if pipeline_run.status == PipelineStatus.RUNNING.value:
                logger.warning(f"Pipeline already running for {run_date}")
                return None

            if not force and pipeline_run.status == PipelineStatus.COMPLETED.value:
                logger.info(f"Pipeline already completed for {run_date} (use force=True to re-run)")
                return None

            # force=True  OR  status is FAILED / PENDING → reset and re-use
            logger.info(f"Resetting pipeline run for {run_date} "
                        f"(previous status={pipeline_run.status}) — force={force}")
            pipeline_run.status = PipelineStatus.PENDING.value
            pipeline_run.step = None
            pipeline_run.error_log = None
            pipeline_run.started_at = None
            pipeline_run.completed_at = None
            pipeline_run.total_symbols = 0
            pipeline_run.processed_symbols = 0
            pipeline_run.total_reports = 0
            pipeline_run.processed_reports = 0
            await db.commit()
            await db.refresh(pipeline_run)
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
            # PRE-FLIGHT: Load active LLM token
            # =============================================
            token_result = await db.execute(
                select(LlmToken).where(LlmToken.is_active == True).limit(1)
            )
            active_token = token_result.scalars().first()
            if not active_token:
                msg = "No active LLM token found. Add a token via /api/admin/llm-tokens and set it active."
                logger.error(f"Pipeline aborted: {msg}")
                pipeline_run.error_log = msg
                await db.commit()
                return False

            llm_api_key = active_token.token
            logger.info(f"Pipeline: Using LLM token from user={active_token.user_id} "
                        f"provider={active_token.provider_name}")

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
            
            # ── Skip symbols that already have signals for this run_date ──
            existing_result = await db.execute(
                select(SignalRecord.symbol)
                .where(SignalRecord.run_date == pipeline_run.run_date)
                .distinct()
            )
            existing_symbols = {row[0] for row in existing_result.all()}

            symbols_to_process = [s for s in all_symbols if s not in existing_symbols]
            skipped_count = len(all_symbols) - len(symbols_to_process)
            if skipped_count:
                logger.info(f"Q1: Skipping {skipped_count} symbols with existing signals "
                            f"for {pipeline_run.run_date}")

            pipeline_run.total_symbols = len(all_symbols)
            await db.commit()
            
            logger.info(f"Q1: Processing {len(symbols_to_process)}/{len(all_symbols)} symbols "
                        f"({len(global_symbols)} global + "
                        f"{len(watchlist_symbols)} watchlist, deduped, "
                        f"{skipped_count} skipped)")
            
            all_signals = await process_symbols_q1(
                symbols=symbols_to_process,
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
                        "ohlcv": stmt.excluded.ohlcv,
                        "indicators": stmt.excluded.indicators,
                        "scope": stmt.excluded.scope,
                        "pipeline_run_id": stmt.excluded.pipeline_run_id,
                        "created_at": stmt.excluded.created_at,
                    },
                )
                await db.execute(stmt)
            
            pipeline_run.processed_symbols = len(all_symbols)
            await db.commit()
            logger.info(f"Q1 DONE: {len(all_signals)} new signals saved "
                        f"({skipped_count} symbols skipped with existing data)")

            # Reload ALL signals for this run_date (including previously-saved
            # ones for skipped symbols) so Q2/Q3 have the full picture.
            if skipped_count:
                existing_rows = await db.execute(
                    select(SignalRecord).where(
                        SignalRecord.run_date == pipeline_run.run_date
                    )
                )
                all_signals_for_reports = [
                    {
                        "run_date": r.run_date,
                        "symbol": r.symbol,
                        "strategy": r.strategy,
                        "signal": r.signal,
                        "confidence": r.confidence,
                        "reason": r.reason,
                        "ohlcv": r.ohlcv,
                        "indicators": r.indicators,
                        "scope": r.scope,
                        "pipeline_run_id": r.pipeline_run_id,
                    }
                    for r in existing_rows.scalars().all()
                ]
                logger.info(f"Q2 input: {len(all_signals_for_reports)} total signals "
                            f"(including {skipped_count} previously-saved)")
            else:
                all_signals_for_reports = all_signals
            
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
                all_signals=all_signals_for_reports,
                pipeline_run_id=pipeline_run.id,
                global_symbols=global_symbols,
                batch_size=self.batch_size,
                max_concurrency=self.max_concurrency,
                identity_key=settings.default_identity,
                api_key=llm_api_key,
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
            symbol_plans: Dict[str, str] = {}
            for rec in global_report_records:
                if rec["report_type"] == "macro_summary":
                    summary_report_md = rec["content_md"]
                elif rec["report_type"] == "symbol_execution_plan" and rec.get("symbol"):
                    symbol_plans[rec["symbol"]] = rec["content_md"]
            
            logger.info(f"Q2 DONE: 1 macro summary + {len(symbol_plans)} execution plans saved")
            
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
                    api_key=llm_api_key,
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
