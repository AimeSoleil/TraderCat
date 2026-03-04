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
import time
from datetime import datetime, date
from typing import List, Dict, Any
from uuid import UUID
from sqlalchemy import select
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
    SymbolVerdict,
    UserBriefing,
    User,
    WatchlistItem,
    GlobalSymbol,
    Strategy,
    LlmToken,
)
from tradercat.pipeline.signal_worker import process_symbols_p1
from tradercat.pipeline.macro_regime_worker import generate_macro_regime_p2
from tradercat.pipeline.execution_plan_worker import generate_execution_plans_p3
from tradercat.pipeline.briefing_worker import (
    generate_user_briefings_p4,
    compress_regime_for_briefing,
)
from tradercat.ai.roles.options_strategist import format_p4_card
from tradercat.pipeline.holidays import is_market_day

logger = get_logger(__name__)


class PipelineOrchestrator:
    """Orchestrates the 4-phase pipeline execution."""

    def __init__(self):
        self.max_concurrency = settings.pipeline_max_concurrency

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

        Each phase uses its own short-lived DB session so the connection is
        returned to the pool between phases.  This prevents the API read
        queries from being starved when the pipeline runs in the same process.
        """
        run_date = run_date or datetime.utcnow().date()

        if not is_market_day(run_date):
            logger.info(f"Skipping pipeline for {run_date} - not a market day")
            return False

        # -- Short session: create / reset pipeline_run --
        async with AsyncSessionLocal() as db:
            pipeline_run = await self._get_or_create_pipeline_run(db, run_date, force=force)
            if pipeline_run is None:
                return False

            pipeline_run.status = PipelineStatus.RUNNING.value
            pipeline_run.started_at = datetime.utcnow()
            await db.commit()
            run_id = pipeline_run.id  # detached after session closes

        try:
            success = await self._execute_pipeline(run_id, run_date)

            async with AsyncSessionLocal() as db:
                pr = await db.get(PipelineRun, run_id)
                if pr:
                    pr.status = PipelineStatus.COMPLETED.value if success else PipelineStatus.FAILED.value
                    pr.completed_at = datetime.utcnow()
                    await db.commit()

            return success

        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            async with AsyncSessionLocal() as db:
                pr = await db.get(PipelineRun, run_id)
                if pr:
                    pr.status = PipelineStatus.FAILED.value
                    pr.error_log = str(e)
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
        self, run_id: UUID, run_date: date
    ) -> bool:
        """Execute the 4-phase pipeline with per-phase DB sessions.

        Each phase opens and closes its own session so the DB connection
        is returned to the pool between phases, allowing API queries to
        proceed without contention.
        """
        current_step = "pre-flight"
        try:
            # =============================================
            # PRE-FLIGHT: Load active LLM token
            # =============================================
            async with AsyncSessionLocal() as db:
                token_result = await db.execute(
                    select(LlmToken).where(LlmToken.is_active == True).limit(1)
                )
                active_token = token_result.scalars().first()
                if not active_token:
                    msg = "No active LLM token found. Add a token via /api/admin/llm-tokens and set it active."
                    logger.error(f"Pipeline aborted: {msg}")
                    pr = await db.get(PipelineRun, run_id)
                    if pr:
                        pr.error_log = msg
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
            current_step = "p1_signals"
            p1_start = time.time()
            logger.info("=" * 60)
            logger.info("PHASE 1 (P1): Signal Generation")
            logger.info("=" * 60)

            async with AsyncSessionLocal() as db:
                pr = await db.get(PipelineRun, run_id)
                pr.step = "p1_signals"
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
                    .where(SignalRecord.run_date == run_date)
                    .distinct()
                )
                existing_symbols = {row[0] for row in existing_result.all()}
                symbols_to_process = [s for s in all_symbols if s not in existing_symbols]
                skipped_count = len(all_symbols) - len(symbols_to_process)
                if skipped_count:
                    logger.info(f"P1: Skipping {skipped_count} symbols with existing signals")

                pr.total_symbols = len(all_symbols)
                await db.commit()

            # -- CPU / network-heavy work outside any session --
            logger.info(
                f"P1: Processing {len(symbols_to_process)}/{len(all_symbols)} symbols "
                f"({len(global_symbols)} global + {len(watchlist_symbols)} watchlist, "
                f"deduped, {skipped_count} skipped)"
            )

            all_signals = await process_symbols_p1(
                symbols=symbols_to_process,
                run_date=run_date,
                pipeline_run_id=run_id,
                max_concurrency=self.max_concurrency,
                strategy_configs=strategy_configs,
            )

            # -- Short session: save signals --
            async with AsyncSessionLocal() as db:
                for idx, signal_data in enumerate(all_signals):
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
                    if idx % 20 == 19:
                        await asyncio.sleep(0)  # yield to event loop

                pr = await db.get(PipelineRun, run_id)
                pr.processed_symbols = len(all_symbols)
                await db.commit()
                p1_elapsed = time.time() - p1_start
                logger.info(f"P1 DONE: {len(all_signals)} new signals saved ({skipped_count} skipped) — {p1_elapsed:.1f}s")

                # Reload ALL signals for this run_date (scoped to current symbols)
                if skipped_count:
                    existing_rows = await db.execute(
                        select(SignalRecord).where(
                            SignalRecord.run_date == run_date,
                            SignalRecord.symbol.in_(all_symbols),
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
                    logger.info(f"P2 input: {len(all_signals_for_reports)} total signals")
                else:
                    all_signals_for_reports = all_signals

            # =============================================
            # PHASE 2 (P2): Macro Regime Analysis
            # =============================================
            current_step = "p2_macro_regime"
            p2_start = time.time()
            logger.info("=" * 60)
            logger.info("PHASE 2 (P2): Macro Regime Analysis")
            logger.info("=" * 60)

            async with AsyncSessionLocal() as db:
                pr = await db.get(PipelineRun, run_id)
                pr.step = "p2_macro_regime"
                await db.commit()

            regime_record = await generate_macro_regime_p2(
                run_date=run_date,
                all_signals=all_signals_for_reports,
                pipeline_run_id=run_id,
                global_symbols=global_symbols,
                api_key=llm_api_key,
            )

            regime_context_md = ""
            regime_label = None
            regime_score = None

            async with AsyncSessionLocal() as db:
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
                    p2_elapsed = time.time() - p2_start
                    logger.info(
                        f"P2 DONE: regime={regime_label}, score={regime_score}, "
                        f"{len(regime_context_md)} chars — {p2_elapsed:.1f}s"
                    )
                else:
                    p2_elapsed = time.time() - p2_start
                    logger.warning(f"P2: No regime context generated — proceeding with empty context ({p2_elapsed:.1f}s)")

            # =============================================
            # PHASE 3 (P3): Per-Symbol Execution Plans
            # =============================================
            current_step = "p3_execution_plans"
            p3_start = time.time()
            logger.info("=" * 60)
            logger.info("PHASE 3 (P3): Per-Symbol Execution Plans")
            logger.info("=" * 60)

            async with AsyncSessionLocal() as db:
                pr = await db.get(PipelineRun, run_id)
                pr.step = "p3_execution_plans"
                await db.commit()

            exec_plan_records = await generate_execution_plans_p3(
                run_date=run_date,
                all_signals=all_signals_for_reports,
                pipeline_run_id=run_id,
                global_symbols=global_symbols,
                regime_context_md=regime_context_md,
                max_concurrency=self.max_concurrency,
                api_key=llm_api_key,
                allowed_symbols=set(all_symbols),
            )

            # Unpack P3 results
            verdict_records = exec_plan_records["verdict_records"]
            plan_records = exec_plan_records["exec_plan_records"]
            symbol_plans_data: Dict[str, Dict] = exec_plan_records["symbol_plans_data"]

            # -- Short session: upsert verdicts + execution plans --
            async with AsyncSessionLocal() as db:
                # Upsert verdict records into symbol_verdicts
                for idx, vr in enumerate(verdict_records):
                    stmt = pg_insert(SymbolVerdict).values(**vr)
                    stmt = stmt.on_conflict_do_update(
                        constraint="uq_verdict_run_date_symbol",
                        set_={c: stmt.excluded[c] for c in vr if c not in ("id", "run_date", "symbol")},
                    )
                    await db.execute(stmt)
                    if idx % 10 == 9:
                        await asyncio.sleep(0)

                # Upsert execution plan records into symbol_execution_plans
                for idx, pr in enumerate(plan_records):
                    stmt = pg_insert(SymbolExecutionPlan).values(**pr)
                    stmt = stmt.on_conflict_do_update(
                        constraint="uq_exec_plan_run_date_symbol",
                        set_={c: stmt.excluded[c] for c in pr if c not in ("id", "run_date", "symbol")},
                    )
                    await db.execute(stmt)
                    if idx % 10 == 9:
                        await asyncio.sleep(0)

                await db.commit()
                p3_elapsed = time.time() - p3_start
                logger.info(
                    f"P3 DONE: {len(verdict_records)} verdicts, "
                    f"{len(plan_records)} execution plans saved "
                    f"({len(symbol_plans_data)} symbols with structured data) — {p3_elapsed:.1f}s"
                )

            # =============================================
            # PHASE 4 (P4): User Briefings
            # =============================================
            current_step = "p4_user_briefings"
            p4_start = time.time()
            logger.info("=" * 60)
            logger.info("PHASE 4 (P4): User Briefings")
            logger.info("=" * 60)

            # Build compressed regime summary for P4
            regime_summary = compress_regime_for_briefing(
                regime_context_md,
                regime_label=regime_label,
                regime_score=regime_score,
            )

            async with AsyncSessionLocal() as db:
                pr = await db.get(PipelineRun, run_id)
                pr.step = "p4_user_briefings"
                await db.commit()

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

                    # Build compressed symbol plans for this user's watchlist
                    user_symbol_plans = {}
                    for sym in user_symbols:
                        if sym in symbol_plans_data:
                            user_symbol_plans[sym] = format_p4_card(symbol_plans_data[sym])

                    user_tasks.append({
                        "user_id": user.id,
                        "run_date": run_date,
                        "regime_summary": regime_summary,
                        "symbol_plans": user_symbol_plans,
                        "pipeline_run_id": run_id,
                    })

                pr.total_reports = len(user_tasks)
                await db.commit()
            logger.info(f"P4: Generating briefings for {len(user_tasks)} users")

            if user_tasks:
                briefing_records = await generate_user_briefings_p4(
                    user_tasks=user_tasks,
                    max_concurrency=self.max_concurrency,
                    api_key=llm_api_key,
                )

                async with AsyncSessionLocal() as db:
                    for idx, briefing_data in enumerate(briefing_records):
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
                        if idx % 10 == 9:
                            await asyncio.sleep(0)  # yield to event loop

                    pr = await db.get(PipelineRun, run_id)
                    pr.processed_reports = len(briefing_records)
                    await db.commit()
                    p4_elapsed = time.time() - p4_start
                    logger.info(f"P4 DONE: {len(briefing_records)} user briefings saved — {p4_elapsed:.1f}s")
            else:
                p4_elapsed = time.time() - p4_start
                logger.info(f"P4: No users to brief — {p4_elapsed:.1f}s")

            # =============================================
            # COMPLETE
            # =============================================
            async with AsyncSessionLocal() as db:
                pr = await db.get(PipelineRun, run_id)
                pr.step = "completed"
                await db.commit()

            logger.info("=" * 60)
            total_elapsed = time.time() - p1_start
            logger.info("PIPELINE COMPLETE")
            logger.info(f"  P1 Signals: {len(all_signals)} — {p1_elapsed:.1f}s")
            logger.info(f"  P2 Regime: {regime_label or 'N/A'} (score={regime_score}) — {p2_elapsed:.1f}s")
            logger.info(f"  P3 Execution Plans: {len(plan_records)} plans, {len(verdict_records)} verdicts — {p3_elapsed:.1f}s")
            logger.info(f"  P4 User Briefings: {len(user_tasks)} — {p4_elapsed:.1f}s")
            logger.info(f"  Total: {total_elapsed:.1f}s")
            logger.info("=" * 60)

            return True

        except Exception as e:
            logger.error(f"Pipeline step '{current_step}' failed: {e}", exc_info=True)
            async with AsyncSessionLocal() as db:
                pr = await db.get(PipelineRun, run_id)
                if pr:
                    pr.error_log = f"[{current_step}] {str(e)}"
                    await db.commit()
            return False
