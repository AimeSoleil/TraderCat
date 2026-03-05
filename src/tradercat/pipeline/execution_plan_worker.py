"""Execution plan worker for pipeline P3 — Tier 3 architecture.

Two-phase P3:
  P3a (Gate Audit): Large batch → JSON verdict per symbol
  P3b (Execution Plans): Only APPROVED symbols → JSON execution plans

Token optimization:
  - P3a batches 20+ symbols (compact JSON verdict output ~50 tokens/symbol)
  - P3b only runs for approved symbols (quality not REJECT/C, direction not NEUTRAL)
  - Rejected symbols get minimal markdown from P3a verdict only → ~80% output savings
  - Sends compressed regime context (Section 4 only)
  - OHLCV de-duplicated and compressed
  - Shared indicators hoisted to symbol-level
  - Hold signals stripped
  - Historical signals grouped by date
  - Compact JSON serialization
"""
import asyncio
import json
import time
from datetime import date
from typing import List, Dict, Any, Optional
from uuid import UUID

from tradercat.logger import get_logger
from tradercat.config import settings
from tradercat.ai.providers.llm_interface import LLMProvider
from tradercat.ai.roles.identity import IdentityRole
from tradercat.ai.llm_progress_logger import llm_worker_context
from tradercat.ai.roles.options_strategist import (
    OptionsStrategistRole,
    extract_downstream_filters,
    build_batch_payload,
    build_p3b_payload,
    parse_json_output,
    render_plan_markdown,
    validate_verdicts,
    validate_execution_plans,
)

logger = get_logger(__name__)


def _json_safe(obj: Any) -> Any:
    """Round-trip through JSON so every value is JSON-serializable."""
    return json.loads(json.dumps(obj, default=str))


def _get_llm_provider(model_id: str = None):
    from tradercat.ai.llm_provider_factory import LLMFactory
    model_id = model_id or settings.default_llm_model
    provider_key = settings.default_llm_provider
    provider, resolved_model = LLMFactory.create_provider(f"{provider_key}_{model_id}")
    return provider, resolved_model


class GateAuditWorker:
    """Worker for P3a: gate audit → JSON verdicts."""

    _P3_IDENTITY = "options_strategist"

    def __init__(
        self,
        max_retries: int | None = None,
        model_id: str | None = None,
        api_key: str | None = None,
    ):
        self.max_retries = max_retries if max_retries is not None else settings.pipeline_llm_max_retries
        self.model_id = model_id or settings.default_llm_model
        self.api_key = api_key
        self._provider: Optional[LLMProvider] = None
        self._strategist: Optional[OptionsStrategistRole] = None

    def _ensure_roles(self):
        if self._strategist is not None:
            return
        try:
            self._provider, self.model_id = _get_llm_provider(self.model_id)
        except Exception as e:
            logger.warning(f"P3a: Failed to init LLM provider: {e}")
            self._provider = None
            return
        identity = IdentityRole(self._P3_IDENTITY)
        self._strategist = OptionsStrategistRole(
            self._provider, identity, self.model_id, api_key=self.api_key
        )

    async def audit_batch(
        self,
        batch_symbols: List[str],
        signals_by_symbol: Dict[str, List[Dict[str, Any]]],
        historical_by_symbol: Dict[str, List[Dict[str, Any]]],
        regime_context_md: str,
    ) -> List[Dict[str, Any]]:
        """Run P3a gate audit for a batch. Returns list of verdict dicts."""
        self._ensure_roles()

        combined_json = build_batch_payload(
            batch_symbols=batch_symbols,
            signals_by_symbol={s: signals_by_symbol.get(s, []) for s in batch_symbols},
            historical_by_symbol={s: historical_by_symbol.get(s, []) for s in batch_symbols},
        )
        compressed_context = extract_downstream_filters(regime_context_md)

        for attempt in range(self.max_retries + 1):
            try:
                if not self._strategist:
                    return self._placeholder_verdicts(batch_symbols)

                result = await self._strategist.gate_audit_batch(
                    symbol_data_json=combined_json,
                    global_context=compressed_context,
                )
                raw = result.content or ""
                logger.info(f"P3a: Batch audit returned {len(raw)} chars for {len(batch_symbols)} symbols")

                verdicts = parse_json_output(raw)
                if not verdicts:
                    logger.warning(f"P3a: JSON parse failed, falling back to placeholder for {batch_symbols}")
                    return self._placeholder_verdicts(batch_symbols)

                # Validate and sanitize verdict schemas
                verdicts = validate_verdicts(verdicts)

                # Normalize: ensure every batch symbol has a verdict
                verdicts_by_sym = {v.get("symbol", "").upper(): v for v in verdicts}
                result_list = []
                for sym in batch_symbols:
                    v = verdicts_by_sym.get(sym)
                    if v:
                        v["symbol"] = sym  # normalize case
                        result_list.append(v)
                    else:
                        logger.warning(f"P3a: No verdict for {sym}, marking NEUTRAL")
                        result_list.append(self._neutral_verdict(sym))
                return result_list

            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(f"P3a: Retry {attempt + 1}/{self.max_retries}: {e}")
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"P3a: Failed batch {batch_symbols} after {self.max_retries + 1} attempts: {e}")

        return self._placeholder_verdicts(batch_symbols)

    @staticmethod
    def _neutral_verdict(symbol: str) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "direction": "NEUTRAL",
            "quality": "C",
            "rr_estimate": "0:0",
            "confluence": "",
            "confluence_count": 0,
            "setup_type": "",
            "historical_trend": "MIXED",
            "gates": "0:P|1:F|2:-|3:-|4:-|5:-|6:-",
            "rejection_reason": "No verdict from LLM",
            "recommended_strategy_type": None,
            "technicals": {},
        }

    @staticmethod
    def _placeholder_verdicts(symbols: List[str]) -> List[Dict[str, Any]]:
        return [GateAuditWorker._neutral_verdict(s) for s in symbols]


class ExecutionPlanWorker:
    """Worker for P3b: execution plans for approved symbols."""

    _P3_IDENTITY = "options_strategist"

    def __init__(
        self,
        max_retries: int | None = None,
        model_id: str | None = None,
        api_key: str | None = None,
    ):
        self.max_retries = max_retries if max_retries is not None else settings.pipeline_llm_max_retries
        self.model_id = model_id or settings.default_llm_model
        self.api_key = api_key
        self._provider: Optional[LLMProvider] = None
        self._strategist: Optional[OptionsStrategistRole] = None

    def _ensure_roles(self):
        if self._strategist is not None:
            return
        try:
            self._provider, self.model_id = _get_llm_provider(self.model_id)
        except Exception as e:
            logger.warning(f"P3b: Failed to init LLM provider: {e}")
            self._provider = None
            return
        identity = IdentityRole(self._P3_IDENTITY)
        self._strategist = OptionsStrategistRole(
            self._provider, identity, self.model_id, api_key=self.api_key
        )

    async def generate_batch(
        self,
        batch_symbols: List[str],
        signals_by_symbol: Dict[str, List[Dict[str, Any]]],
        verdicts_by_symbol: Dict[str, Dict[str, Any]],
        regime_context_md: str,
    ) -> Dict[str, Dict[str, Any]]:
        """
        P3b: Generate execution plans for a batch of approved symbols.

        Returns dict mapping symbol → execution plan JSON.
        """
        self._ensure_roles()

        combined_json = build_p3b_payload(
            batch_symbols=batch_symbols,
            signals_by_symbol={s: signals_by_symbol.get(s, []) for s in batch_symbols},
            verdicts_by_symbol={s: verdicts_by_symbol.get(s, {}) for s in batch_symbols},
        )
        compressed_context = extract_downstream_filters(regime_context_md)

        for attempt in range(self.max_retries + 1):
            try:
                if not self._strategist:
                    return {}

                result = await self._strategist.analyze_batch(
                    symbol_data_json=combined_json,
                    global_context=compressed_context,
                )
                raw = result.content or ""
                logger.info(f"P3b: Batch returned {len(raw)} chars for {len(batch_symbols)} symbols")

                plans = parse_json_output(raw)
                if not plans:
                    logger.warning(f"P3b: JSON parse failed for {batch_symbols}")
                    return {}

                # Validate and sanitize execution plan schemas
                plans = validate_execution_plans(plans)

                plans_by_sym: Dict[str, Dict[str, Any]] = {}
                for plan in plans:
                    sym = (plan.get("symbol") or "").upper()
                    if sym in batch_symbols:
                        plans_by_sym[sym] = plan
                return plans_by_sym

            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(f"P3b: Retry {attempt + 1}/{self.max_retries}: {e}")
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"P3b: Failed batch {batch_symbols}: {e}")

        return {}


def is_approved(verdict: Dict[str, Any]) -> bool:
    """Check if a P3a verdict is approved for P3b execution planning.
    
    Approved = quality in (A+, A, B+, B) AND direction not NEUTRAL.
    REJECT, C, WATCHLIST are not approved (C/WATCHLIST need human review, REJECT hard fails).
    """
    quality = (verdict.get("quality") or "").upper()
    direction = (verdict.get("direction") or "").upper()
    return quality not in ("REJECT", "C", "WATCHLIST") and direction != "NEUTRAL"


def _safe_float(val: Any) -> Optional[float]:
    """Safely convert a value to float, returning None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any) -> Optional[int]:
    """Safely convert a value to int, returning None on failure."""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def build_verdict_record(
    verdict: Dict[str, Any],
    run_date: date,
    pipeline_run_id: UUID,
) -> Dict[str, Any]:
    """Build a DB record dict for the symbol_verdicts table from a P3a verdict."""
    tech = verdict.get("technicals") or {}
    squeeze_val = tech.get("volatility_squeeze")
    squeeze_bool = None
    if squeeze_val is not None:
        squeeze_bool = bool(squeeze_val) if not isinstance(squeeze_val, str) else squeeze_val.lower() in ("true", "yes", "y", "1")

    return {
        "run_date": run_date,
        "symbol": verdict.get("symbol", ""),
        # Core verdict
        "direction": (verdict.get("direction") or "NEUTRAL").upper(),
        "quality": (verdict.get("quality") or "C").upper(),
        "confidence": _safe_float(verdict.get("confidence")),
        "rr_estimate": verdict.get("rr_estimate"),
        "setup_type": verdict.get("setup_type"),
        # Confluence
        "confluence": verdict.get("confluence"),
        "confluence_count": _safe_int(verdict.get("confluence_count")),
        # Historical continuity
        "historical_trend": verdict.get("historical_trend"),
        # Gate results
        "gates": verdict.get("gates"),
        "rejection_reason": verdict.get("rejection_reason"),
        # Trend (Gate 3)
        "trend_adx": _safe_float(tech.get("trend_adx")),
        "trend_ema_fast": _safe_float(tech.get("trend_ema_fast")),
        "trend_ema_slow": _safe_float(tech.get("trend_ema_slow")),
        "trend_ema_spread_pct": _safe_float(tech.get("trend_ema_spread_pct")),
        "trend_pct_b": _safe_float(tech.get("trend_pct_b")),
        # Momentum (Gate 4)
        "momentum_rsi": _safe_float(tech.get("momentum_rsi")),
        "momentum_macd_hist": _safe_float(tech.get("momentum_macd_hist")),
        "momentum_mom_score": _safe_float(tech.get("momentum_mom_score")),
        # Volume (Gate 5)
        "volume_rel": _safe_float(tech.get("volume_rel")),
        "volume_zscore": _safe_float(tech.get("volume_zscore")),
        "volume_classification": tech.get("volume_classification"),
        # Volatility
        "volatility_atr_pct": _safe_float(tech.get("volatility_atr_pct")),
        "volatility_bandwidth": _safe_float(tech.get("volatility_bandwidth")),
        "volatility_squeeze": squeeze_bool,
        # Key levels
        "key_level_support": _safe_float(tech.get("key_level_support")),
        "key_level_resistance": _safe_float(tech.get("key_level_resistance")),
        # Strategy recommendation
        "recommended_strategy_type": verdict.get("recommended_strategy_type"),
        # Raw JSON
        "raw_json": _json_safe(verdict),
        # Metadata
        "model_used": settings.default_llm_model,
        "identity_used": "options_strategist",
        "pipeline_run_id": pipeline_run_id,
    }


def build_exec_plan_record(
    plan: Dict[str, Any],
    run_date: date,
    pipeline_run_id: UUID,
    content_md: str = "",
) -> Dict[str, Any]:
    """Build a DB record dict for the symbol_execution_plans table from a P3b plan."""
    return {
        "run_date": run_date,
        "symbol": (plan.get("symbol") or "").upper(),
        # Trade structure
        "structure": plan.get("structure"),
        "direction": plan.get("direction"),
        "thesis": plan.get("thesis"),
        "rationale": plan.get("rationale"),
        # Legs (JSON array)
        "legs": _json_safe(plan.get("legs", [])),
        # Entry
        "entry_trigger": plan.get("entry_trigger"),
        # Risk parameters
        "stop_loss": plan.get("stop_loss"),
        "profit_target": plan.get("profit_target"),
        "time_stop": plan.get("time_stop"),
        "max_loss": plan.get("max_loss"),
        "max_profit": plan.get("max_profit"),
        "breakeven": plan.get("breakeven"),
        "rr_ratio": plan.get("rr_ratio") or plan.get("rr"),
        # Allocation & sizing
        "allocation": plan.get("allocation"),
        "dte": _safe_int(plan.get("dte")),
        # Content
        "content_md": content_md or None,
        # Raw JSON
        "raw_json": _json_safe(plan),
        # Metadata
        "model_used": settings.default_llm_model,
        "identity_used": "options_strategist",
        "pipeline_run_id": pipeline_run_id,
    }


async def generate_execution_plans_p3(
    run_date: date,
    all_signals: List[Dict[str, Any]],
    pipeline_run_id: UUID,
    global_symbols: List[str],
    regime_context_md: str,
    max_concurrency: int = 3,
    api_key: str | None = None,
    allowed_symbols: set[str] | None = None,
) -> Dict[str, Any]:
    """
    P3 entry point: Two-phase execution plan generation.

    Phase 3a: Gate audit all symbols in large batches (20+)
    Phase 3b: Execution plans only for approved symbols in small batches (3)

    Returns dict with keys:
      - verdict_records: list of DB record dicts for symbol_verdicts table
      - exec_plan_records: list of DB record dicts for symbol_execution_plans table
      - symbol_plans_data: dict mapping symbol → {verdict, execution} for P4 consumption
    """
    # --- Fetch historical signals + execution plans (past 1 trading day) ---
    historical_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    try:
        from tradercat.pipeline.holidays import get_previous_market_day
        past_dates: List[date] = []
        d = run_date
        for _ in range(1):
            d = get_previous_market_day(d)
            past_dates.append(d)

        from tradercat.database import AsyncSessionLocal
        from tradercat.models import SignalRecord, SymbolExecutionPlan
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            stmt = (
                select(SignalRecord)
                .where(SignalRecord.run_date.in_(past_dates))
                .order_by(SignalRecord.run_date.desc())
            )
            result = await db.execute(stmt)
            for row in result.scalars().all():
                historical_by_symbol.setdefault(row.symbol, []).append({
                    "run_date": str(row.run_date),
                    "symbol": row.symbol,
                    "strategy": row.strategy,
                    "signal": row.signal,
                    "confidence": row.confidence,
                    "ohlcv": row.ohlcv or {},
                    "indicators": row.indicators or {},
                })

            plan_stmt = (
                select(SymbolExecutionPlan)
                .where(SymbolExecutionPlan.run_date.in_(past_dates))
            )
            plan_result = await db.execute(plan_stmt)
            for plan_row in plan_result.scalars().all():
                entries = historical_by_symbol.get(plan_row.symbol, [])
                if entries:
                    entries[0]["execution_plan_md"] = plan_row.content_md or ""

        total_hist = sum(len(v) for v in historical_by_symbol.values())
        logger.info(f"P3: Loaded {total_hist} historical signals for {len(historical_by_symbol)} symbols")
    except Exception as e:
        logger.warning(f"P3: Failed to load historical signals: {e}")

    # --- Determine plan-eligible symbols (exclude macro-only ETFs) ---
    keep_global = {"QQQ", "SPY", "IWM"}
    excluded_global = set(global_symbols) - keep_global

    signals_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    plan_symbols: List[str] = []
    skipped_out_of_scope = 0
    for sig in all_signals:
        sym = sig["symbol"]
        # Skip symbols not in the allowed scope (watchlist + global)
        if allowed_symbols is not None and sym not in allowed_symbols:
            skipped_out_of_scope += 1
            continue
        signals_by_symbol.setdefault(sym, []).append(sig)
        if sym not in plan_symbols and sym not in excluded_global:
            plan_symbols.append(sym)

    if skipped_out_of_scope:
        logger.info(f"P3: Filtered out {skipped_out_of_scope} signals from symbols outside watchlist+global scope")
    logger.info(f"P3: {len(plan_symbols)} symbols (excluded {len(excluded_global)} macro-only ETFs)")

    # ═══════════════════════════════════════════════
    # PHASE 3a: Gate Audit (large batches)
    # ═══════════════════════════════════════════════
    audit_batch_size = settings.pipeline_audit_batch_size
    audit_batches = [plan_symbols[i:i + audit_batch_size] for i in range(0, len(plan_symbols), audit_batch_size)]

    all_verdicts: List[Dict[str, Any]] = []

    audit_queue: asyncio.Queue = asyncio.Queue()
    for batch in audit_batches:
        await audit_queue.put(batch)

    # Shared progress counter for concurrent P3a workers
    p3a_progress = {"processed": 0, "total": len(plan_symbols)}
    p3a_start = time.time()
    num_audit_workers = min(max_concurrency, len(audit_batches) or 1)

    async def audit_worker_fn(worker_id: int):
        wname = f"P3a-W{worker_id}"
        results = []
        worker = GateAuditWorker(api_key=api_key)
        while True:
            try:
                batch = audit_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                llm_worker_context.set(f"{wname} [{', '.join(batch)}]")
                logger.info(
                    "%s: Auditing [%s] — %d/%d processed, %d remaining",
                    wname,
                    ", ".join(batch),
                    p3a_progress["processed"],
                    p3a_progress["total"],
                    p3a_progress["total"] - p3a_progress["processed"],
                )
                verdicts = await worker.audit_batch(
                    batch_symbols=batch,
                    signals_by_symbol=signals_by_symbol,
                    historical_by_symbol=historical_by_symbol,
                    regime_context_md=regime_context_md,
                )
                results.extend(verdicts)
                p3a_progress["processed"] += len(batch)
                elapsed = time.time() - p3a_start
                logger.info(
                    "%s: Batch [%s] done — %d/%d processed, %d remaining (%.1fs elapsed)",
                    wname,
                    ", ".join(batch),
                    p3a_progress["processed"],
                    p3a_progress["total"],
                    p3a_progress["total"] - p3a_progress["processed"],
                    elapsed,
                )
            finally:
                audit_queue.task_done()
        logger.info(f"{wname}: Finished — {len(results)} verdicts produced")
        return results

    logger.info(f"P3a: Spawning {num_audit_workers} workers for {len(audit_batches)} batches ({len(plan_symbols)} symbols)")
    audit_workers = [
        asyncio.create_task(audit_worker_fn(i + 1))
        for i in range(num_audit_workers)
    ]
    audit_results = await asyncio.gather(*audit_workers)
    for result_list in audit_results:
        all_verdicts.extend(result_list)

    verdicts_by_symbol = {v["symbol"]: v for v in all_verdicts}

    approved_symbols = [v["symbol"] for v in all_verdicts if is_approved(v)]
    rejected_symbols = [v["symbol"] for v in all_verdicts if not is_approved(v)]

    logger.info(
        f"P3a DONE: {len(approved_symbols)} APPROVED, {len(rejected_symbols)} REJECTED/WATCHLIST "
        f"(from {len(all_verdicts)} audited)"
    )

    # ═══════════════════════════════════════════════
    # PHASE 3b: Execution Plans (small batches, approved only)
    # ═══════════════════════════════════════════════
    exec_batch_size = settings.pipeline_exec_batch_size
    exec_batches = [approved_symbols[i:i + exec_batch_size] for i in range(0, len(approved_symbols), exec_batch_size)]

    exec_plans_by_symbol: Dict[str, Dict[str, Any]] = {}

    exec_queue: asyncio.Queue = asyncio.Queue()
    for batch in exec_batches:
        await exec_queue.put(batch)

    # Shared progress counter for concurrent P3b workers
    p3b_progress = {"processed": 0, "total": len(approved_symbols)}
    p3b_start = time.time()
    num_exec_workers = min(max_concurrency, len(exec_batches) or 1)

    async def exec_worker_fn(worker_id: int):
        wname = f"P3b-W{worker_id}"
        results: Dict[str, Dict[str, Any]] = {}
        worker = ExecutionPlanWorker(api_key=api_key)
        while True:
            try:
                batch = exec_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                llm_worker_context.set(f"{wname} [{', '.join(batch)}]")
                logger.info(
                    "%s: Planning [%s] — %d/%d processed, %d remaining",
                    wname,
                    ", ".join(batch),
                    p3b_progress["processed"],
                    p3b_progress["total"],
                    p3b_progress["total"] - p3b_progress["processed"],
                )
                plans = await worker.generate_batch(
                    batch_symbols=batch,
                    signals_by_symbol=signals_by_symbol,
                    verdicts_by_symbol=verdicts_by_symbol,
                    regime_context_md=regime_context_md,
                )
                results.update(plans)
                p3b_progress["processed"] += len(batch)
                elapsed = time.time() - p3b_start
                logger.info(
                    "%s: Batch [%s] done — %d/%d processed, %d remaining (%.1fs elapsed)",
                    wname,
                    ", ".join(batch),
                    p3b_progress["processed"],
                    p3b_progress["total"],
                    p3b_progress["total"] - p3b_progress["processed"],
                    elapsed,
                )
            finally:
                exec_queue.task_done()
        logger.info(f"{wname}: Finished — {len(results)} plans produced")
        return results

    logger.info(f"P3b: Spawning {num_exec_workers} workers for {len(exec_batches)} batches ({len(approved_symbols)} approved symbols)")
    exec_workers = [
        asyncio.create_task(exec_worker_fn(i + 1))
        for i in range(num_exec_workers)
    ]
    exec_results = await asyncio.gather(*exec_workers)
    for result_dict in exec_results:
        exec_plans_by_symbol.update(result_dict)

    logger.info(f"P3b DONE: {len(exec_plans_by_symbol)} execution plans generated")

    # ═══════════════════════════════════════════════
    # MERGE: Build DB records for both tables + P4 data
    # ═══════════════════════════════════════════════
    verdict_records: List[Dict[str, Any]] = []
    exec_plan_records: List[Dict[str, Any]] = []
    symbol_plans_data: Dict[str, Dict[str, Any]] = {}

    for symbol in plan_symbols:
        verdict = verdicts_by_symbol.get(symbol, GateAuditWorker._neutral_verdict(symbol))
        execution = exec_plans_by_symbol.get(symbol)

        # Build verdict DB record
        verdict_records.append(
            build_verdict_record(verdict, run_date, pipeline_run_id)
        )

        # Build execution plan DB record (only for approved symbols with plans)
        if execution:
            content_md = render_plan_markdown(verdict, execution)
            exec_plan_records.append(
                build_exec_plan_record(execution, run_date, pipeline_run_id, content_md)
            )

        # Build P4 structured data for downstream consumption
        structured = dict(verdict)
        structured["execution"] = execution
        symbol_plans_data[symbol] = structured

    logger.info(
        f"P3 complete: {len(verdict_records)} verdicts, "
        f"{len(exec_plan_records)} execution plans"
    )
    return {
        "verdict_records": verdict_records,
        "exec_plan_records": exec_plan_records,
        "symbol_plans_data": symbol_plans_data,
    }
