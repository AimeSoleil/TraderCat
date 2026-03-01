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
from datetime import date
from typing import List, Dict, Any, Optional
from uuid import UUID

from tradercat.logger import get_logger
from tradercat.config import settings
from tradercat.ai.providers.llm_interface import LLMProvider
from tradercat.ai.roles.identity import IdentityRole
from tradercat.ai.roles.options_strategist import (
    OptionsStrategistRole,
    extract_downstream_filters,
    build_batch_payload,
    build_p3b_payload,
    parse_json_output,
    render_plan_markdown,
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


def _verdict_to_db_verdict(direction: str) -> Optional[str]:
    """Convert P3a direction to DB verdict value."""
    mapping = {"long": "buy", "short": "sell", "neutral": "hold"}
    return mapping.get((direction or "").lower())


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
    """Check if a P3a verdict is approved for P3b execution planning."""
    quality = (verdict.get("quality") or "").upper()
    direction = (verdict.get("direction") or "").upper()
    return quality not in ("REJECT", "C") and direction != "NEUTRAL"


async def generate_execution_plans_p3(
    run_date: date,
    all_signals: List[Dict[str, Any]],
    pipeline_run_id: UUID,
    global_symbols: List[str],
    regime_context_md: str,
    max_concurrency: int = 3,
    api_key: str | None = None,
) -> List[Dict[str, Any]]:
    """
    P3 entry point: Two-phase execution plan generation.

    Phase 3a: Gate audit all symbols in large batches (20+)
    Phase 3b: Execution plans only for approved symbols in small batches (3)

    Returns list of DB record dicts with structured_data for P4 consumption.
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
    for sig in all_signals:
        sym = sig["symbol"]
        signals_by_symbol.setdefault(sym, []).append(sig)
        if sym not in plan_symbols and sym not in excluded_global:
            plan_symbols.append(sym)

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

    async def audit_worker_fn():
        results = []
        worker = GateAuditWorker(api_key=api_key)
        while True:
            try:
                batch = audit_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                verdicts = await worker.audit_batch(
                    batch_symbols=batch,
                    signals_by_symbol=signals_by_symbol,
                    historical_by_symbol=historical_by_symbol,
                    regime_context_md=regime_context_md,
                )
                results.extend(verdicts)
            finally:
                audit_queue.task_done()
        return results

    audit_workers = [
        asyncio.create_task(audit_worker_fn())
        for _ in range(min(max_concurrency, len(audit_batches) or 1))
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

    async def exec_worker_fn():
        results: Dict[str, Dict[str, Any]] = {}
        worker = ExecutionPlanWorker(api_key=api_key)
        while True:
            try:
                batch = exec_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                plans = await worker.generate_batch(
                    batch_symbols=batch,
                    signals_by_symbol=signals_by_symbol,
                    verdicts_by_symbol=verdicts_by_symbol,
                    regime_context_md=regime_context_md,
                )
                results.update(plans)
            finally:
                exec_queue.task_done()
        return results

    exec_workers = [
        asyncio.create_task(exec_worker_fn())
        for _ in range(min(max_concurrency, len(exec_batches) or 1))
    ]
    exec_results = await asyncio.gather(*exec_workers)
    for result_dict in exec_results:
        exec_plans_by_symbol.update(result_dict)

    logger.info(f"P3b DONE: {len(exec_plans_by_symbol)} execution plans generated")

    # ═══════════════════════════════════════════════
    # MERGE: Build DB records with rendered markdown
    # ═══════════════════════════════════════════════
    all_records: List[Dict[str, Any]] = []

    for symbol in plan_symbols:
        verdict = verdicts_by_symbol.get(symbol, GateAuditWorker._neutral_verdict(symbol))
        execution = exec_plans_by_symbol.get(symbol)

        # Merge verdict + execution into structured_data
        structured_data = dict(verdict)
        structured_data["execution"] = execution

        # Render markdown for DB storage and frontend
        content_md = render_plan_markdown(verdict, execution)

        all_records.append({
            "run_date": run_date,
            "symbol": symbol,
            "verdict": _verdict_to_db_verdict(verdict.get("direction")),
            "setup_quality": verdict.get("quality"),
            "content_md": content_md,
            "model_used": settings.default_llm_model,
            "identity_used": "options_strategist",
            "input_context": _json_safe({
                "batch_symbols": [symbol],
                "symbol": symbol,
                "phase": "p3a+p3b" if execution else "p3a_only",
            }),
            "pipeline_run_id": pipeline_run_id,
            "structured_data": structured_data,
        })

    logger.info(f"P3 complete: {len(all_records)} records ({len(exec_plans_by_symbol)} with execution plans)")
    return all_records
