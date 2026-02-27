"""Pipeline orchestrator — 4-phase pipeline.

Phase 1 (P1): Signal generation for all unique symbols (global + watchlist).
Phase 2 (P2): Macro regime analysis — single global regime context.
Phase 3 (P3): Per-symbol execution plans — batched, concurrent.
Phase 4 (P4): User briefings — personalized, concurrent.

Each phase waits for the previous to complete (barrier pattern).

Token optimization applied at every phase:
  - P2: Compressed OHLCV and indicators (only essential keys).
  - P3: Downstream filters only from P2 (not full markdown); OHLCV de-duped.
  - P4: Compressed regime + condensed execution plan summaries.
"""
import asyncio
from datetime import datetime, date
from typing import List, Dict, Any
from uuid import UUID
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tradercat.logger import get_logger
from tradercat.config import settings
from tradercat.database import AsyncSessionLocal
from tradercat.models import (
    PipelineRun,
    PipelineStatus,
    SignalRecord,
    SignalScope,
    MacroRegimeContext,
    SymbolExecutionPlan,
    UserBriefing,
    User,
    WatchlistItem,
    GlobalSymbol,
    Strategy,
    StrategyPreset,
    LlmToken,
)
from tradercat.pipeline.signal_worker import process_symbols_p1
from tradercat.pipeline.macro_regime_worker import generate_macro_regime_p2
from tradercat.pipeline.execution_plan_worker import generate_execution_plans_p3
from tradercat.pipeline.briefing_worker import (
    generate_user_briefings_p4,
    compress_regime_for_briefing,
    compress_plan_for_briefing,
)
from tradercat.pipeline.holidays import is_market_day

logger = get_logger(__name__)


class PipelineOrchestrator:
    """Orchestrates the 4-phase pipeline execution."""

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
                   PENDING so it can be re-executed.

        Flow: P1 (signals) → P2 (macro regime) → P3 (execution plans) → P4 (user briefings)
        """
        run_date = run_date or datetime.utcnow().date()

        if not is_market_day(run_date):
            logger.info(f"Skipping pipeline for {run_date} - not a market day")
            return False

        async with AsyncSessionLocal() as db:
            try:
                pipeline_run = await self._get_or_create_pipeline_run(db, run_date, force=force)
                if pipeline_run is None:
                    return False

                pipeline_run.status = PipelineStatus.RUNNING.value
                pipeline_run.started_at = datetime.utcnow()
                await db.commit()

                success = await self._execute_pipeline(db, pipeline_run)

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

            logger.info(
                f"Resetting pipeline run for {run_date} "
                f"(previous status={pipeline_run.status}) — force={force}"
            )
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
        """Execute the 4-phase pipeline."""
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
            logger.info(
                f"Pipeline: Using LLM token from user={active_token.user_id} "
                f"provider={active_token.provider_name}"
            )

            # =============================================
            # PHASE 1 (P1): Signal Generation
            # =============================================
            logger.info("=" * 60)
            logger.info("PHASE 1 (P1): Signal Generation")
            logger.info("=" * 60)
            pipeline_run.step = "p1_signals"
            await db.commit()

            # Load active strategies + presets
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
                logger.info(f"P1: Loaded {len(strategy_configs)} active strategies from DB")
            else:
                logger.warning("P1: No active strategies in DB — will use hardcoded fallback")

            # Collect global symbols
            result = await db.execute(
                select(GlobalSymbol.symbol).order_by(GlobalSymbol.symbol_type, GlobalSymbol.symbol)
            )
            global_symbols = [row[0] for row in result.all()]

            if not global_symbols:
                logger.warning("No global symbols configured — falling back to config default")
                global_symbols = settings.global_symbols

            # Collect all unique symbols: global + all watchlists
            result = await db.execute(select(WatchlistItem.symbol).distinct())
            watchlist_symbols = [row[0] for row in result.all()]

            all_symbols = list(dict.fromkeys(global_symbols + watchlist_symbols))

            # Skip symbols with existing signals
            existing_result = await db.execute(
                select(SignalRecord.symbol)
                .where(SignalRecord.run_date == pipeline_run.run_date)
                .distinct()
            )
            existing_symbols = {row[0] for row in existing_result.all()}
            symbols_to_process = [s for s in all_symbols if s not in existing_symbols]
            skipped_count = len(all_symbols) - len(symbols_to_process)
            if skipped_count:
                logger.info(f"P1: Skipping {skipped_count} symbols with existing signals")

            pipeline_run.total_symbols = len(all_symbols)
            await db.commit()

            logger.info(
                f"P1: Processing {len(symbols_to_process)}/{len(all_symbols)} symbols "
                f"({len(global_symbols)} global + {len(watchlist_symbols)} watchlist, "
                f"deduped, {skipped_count} skipped)"
            )

            all_signals = await process_symbols_p1(
                symbols=symbols_to_process,
                run_date=pipeline_run.run_date,
                pipeline_run_id=pipeline_run.id,
                max_concurrency=self.max_concurrency,
                strategy_configs=strategy_configs,
            )

            # Save signals (upsert)
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
            logger.info(f"P1 DONE: {len(all_signals)} new signals saved ({skipped_count} skipped)")

            # Reload ALL signals for this run_date
            if skipped_count:
                existing_rows = await db.execute(
                    select(SignalRecord).where(SignalRecord.run_date == pipeline_run.run_date)
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
                logger.info(f"P2 input: {len(all_signals_for_reports)} total signals")
            else:
                all_signals_for_reports = all_signals

            # =============================================
            # PHASE 2 (P2): Macro Regime Analysis
            # =============================================
            logger.info("=" * 60)
            logger.info("PHASE 2 (P2): Macro Regime Analysis")
            logger.info("=" * 60)
            pipeline_run.step = "p2_macro_regime"
            await db.commit()

            regime_record = await generate_macro_regime_p2(
                run_date=pipeline_run.run_date,
                all_signals=all_signals_for_reports,
                pipeline_run_id=pipeline_run.id,
                global_symbols=global_symbols,
                identity_key=settings.default_identity,
                api_key=llm_api_key,
            )

            regime_context_md = ""
            regime_label = None
            regime_score = None

            if regime_record:
                # Upsert macro regime context
                stmt = pg_insert(MacroRegimeContext).values(**regime_record)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[MacroRegimeContext.run_date],
                    set_={
                        "regime_label": stmt.excluded.regime_label,
                        "regime_score": stmt.excluded.regime_score,
                        "content_md": stmt.excluded.content_md,
                        "downstream_filters": stmt.excluded.downstream_filters,
                        "model_used": stmt.excluded.model_used,
                        "identity_used": stmt.excluded.identity_used,
                        "input_context": stmt.excluded.input_context,
                        "pipeline_run_id": stmt.excluded.pipeline_run_id,
                        "created_at": stmt.excluded.created_at,
                    },
                )
                await db.execute(stmt)
                await db.commit()

                regime_context_md = regime_record["content_md"]
                regime_label = regime_record.get("regime_label")
                regime_score = regime_record.get("regime_score")
                logger.info(
                    f"P2 DONE: regime={regime_label}, score={regime_score}, "
                    f"{len(regime_context_md)} chars"
                )
            else:
                logger.warning("P2: No regime context generated — proceeding with empty context")
                await db.commit()

            # =============================================
            # PHASE 3 (P3): Per-Symbol Execution Plans
            # =============================================
            logger.info("=" * 60)
            logger.info("PHASE 3 (P3): Per-Symbol Execution Plans")
            logger.info("=" * 60)
            pipeline_run.step = "p3_execution_plans"
            await db.commit()

            exec_plan_records = await generate_execution_plans_p3(
                run_date=pipeline_run.run_date,
                all_signals=all_signals_for_reports,
                pipeline_run_id=pipeline_run.id,
                global_symbols=global_symbols,
                regime_context_md=regime_context_md,
                batch_size=self.batch_size,
                max_concurrency=self.max_concurrency,
                identity_key=settings.default_identity,
                api_key=llm_api_key,
            )

            # Upsert execution plans
            symbol_plans_md: Dict[str, str] = {}
            for plan_data in exec_plan_records:
                stmt = pg_insert(SymbolExecutionPlan).values(**plan_data)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_exec_plan_run_date_symbol",
                    set_={
                        "verdict": stmt.excluded.verdict,
                        "setup_quality": stmt.excluded.setup_quality,
                        "content_md": stmt.excluded.content_md,
                        "model_used": stmt.excluded.model_used,
                        "identity_used": stmt.excluded.identity_used,
                        "input_context": stmt.excluded.input_context,
                        "pipeline_run_id": stmt.excluded.pipeline_run_id,
                        "created_at": stmt.excluded.created_at,
                    },
                )
                await db.execute(stmt)
                if plan_data.get("symbol"):
                    symbol_plans_md[plan_data["symbol"]] = plan_data["content_md"]

            await db.commit()
            logger.info(f"P3 DONE: {len(symbol_plans_md)} execution plans saved")

            # =============================================
            # PHASE 4 (P4): User Briefings
            # =============================================
            logger.info("=" * 60)
            logger.info("PHASE 4 (P4): User Briefings")
            logger.info("=" * 60)
            pipeline_run.step = "p4_user_briefings"
            await db.commit()

            # Build compressed regime summary for P4
            regime_summary = compress_regime_for_briefing(
                regime_context_md,
                regime_label=regime_label,
                regime_score=regime_score,
            )

            # Get active users with watchlists
            result = await db.execute(
                select(User).where(User.is_active == True)
            )
            active_users = result.scalars().all()

            user_tasks = []
            for user in active_users:
                result = await db.execute(
                    select(WatchlistItem.symbol).where(WatchlistItem.user_id == user.id)
                )
                user_symbols = [row[0] for row in result.all()]

                if not user_symbols:
                    logger.info(f"P4: Skipping user {user.username} — empty watchlist")
                    continue

                # Filter and compress symbol plans for this user's watchlist
                user_symbol_plans = {}
                for sym in user_symbols:
                    if sym in symbol_plans_md:
                        user_symbol_plans[sym] = compress_plan_for_briefing(symbol_plans_md[sym])

                user_tasks.append({
                    "user_id": user.id,
                    "run_date": pipeline_run.run_date,
                    "regime_summary": regime_summary,
                    "symbol_plans": user_symbol_plans,
                    "pipeline_run_id": pipeline_run.id,
                })

            pipeline_run.total_reports = len(user_tasks)
            await db.commit()
            logger.info(f"P4: Generating briefings for {len(user_tasks)} users")

            if user_tasks:
                briefing_records = await generate_user_briefings_p4(
                    user_tasks=user_tasks,
                    max_concurrency=self.max_concurrency,
                    api_key=llm_api_key,
                )

                for briefing_data in briefing_records:
                    stmt = pg_insert(UserBriefing).values(**briefing_data)
                    stmt = stmt.on_conflict_do_update(
                        constraint="uq_user_briefing_user_run_date",
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

                pipeline_run.processed_reports = len(briefing_records)
                await db.commit()
                logger.info(f"P4 DONE: {len(briefing_records)} user briefings saved")

            # =============================================
            # COMPLETE
            # =============================================
            pipeline_run.step = "completed"
            await db.commit()

            logger.info("=" * 60)
            logger.info("PIPELINE COMPLETE")
            logger.info(f"  P1 Signals: {len(all_signals)}")
            logger.info(f"  P2 Regime: {regime_label or 'N/A'} (score={regime_score})")
            logger.info(f"  P3 Execution Plans: {len(exec_plan_records)}")
            logger.info(f"  P4 User Briefings: {pipeline_run.processed_reports}")
            logger.info("=" * 60)

            return True

        except Exception as e:
            logger.error(f"Pipeline step '{pipeline_run.step}' failed: {e}", exc_info=True)
            pipeline_run.error_log = f"[{pipeline_run.step}] {str(e)}"
            await db.commit()
            return False
