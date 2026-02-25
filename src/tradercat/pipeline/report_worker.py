"""Global report generation worker for pipeline (Q2) — role-based AI.

Q2 uses the 3-role AI infrastructure:
  Phase 2a: Global Analysis — Macro regime + sector rotation (AnalystRole)
  Phase 2b: Symbol Analysis — Per-symbol execution plans (AnalystRole)
  Phase 2c: Portfolio Summary — Consolidated report (SummarizerRole)

These reports are stored in global_reports (no user_id).
"""
import asyncio
import json
from datetime import date
from typing import List, Dict, Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tradercat.logger.logger import get_logger
from tradercat.config import settings
from tradercat.ai.providers.llm_interface import LLMProvider
from tradercat.ai.roles.identity import IdentityRole
from tradercat.ai.roles.analyst import AnalystRole
from tradercat.ai.roles.summarizer import SummarizerRole
from tradercat.pipeline.holidays import get_previous_market_day

logger = get_logger(__name__)


def _json_safe(obj: Any) -> Any:
    """Round-trip through JSON so every value is JSON-serializable (date → str, etc.)."""
    return json.loads(json.dumps(obj, default=str))


def _get_llm_provider(model_id: str = None) -> LLMProvider:
    """Get LLM provider from the factory."""
    from tradercat.ai.llm_provider_factory import LLMFactory
    model_id = model_id or settings.default_llm_model
    provider_key = settings.default_llm_provider
    provider, resolved_model = LLMFactory.create_provider(f"{provider_key}_{model_id}")
    return provider, resolved_model


class GlobalReportWorker:
    """Worker for generating global LLM reports (Q2) using role-based AI."""
    
    def __init__(
        self,
        max_retries: int | None = None,
        identity_key: str | None = None,
        model_id: str | None = None,
        api_key: str | None = None,
    ):
        self.max_retries = max_retries if max_retries is not None else settings.pipeline_llm_max_retries
        self.identity_key = identity_key or settings.default_persona
        self.model_id = model_id or settings.default_llm_model
        self.api_key = api_key
        
        # Lazy init — roles created on first use
        self._provider: Optional[LLMProvider] = None
        self._identity: Optional[IdentityRole] = None
        self._analyst: Optional[AnalystRole] = None
        self._summarizer: Optional[SummarizerRole] = None
    
    def _ensure_roles(self):
        """Initialize AI roles lazily."""
        if self._analyst is not None:
            return
        
        try:
            self._provider, self.model_id = _get_llm_provider(self.model_id)
        except Exception as e:
            logger.warning(f"Q2: Failed to init LLM provider: {e}. Will use fallback.")
            self._provider = None
            return
        
        self._identity = IdentityRole(self.identity_key)
        self._analyst = AnalystRole(self._provider, self._identity, self.model_id, api_key=self.api_key)
        self._summarizer = SummarizerRole(self._provider, self._identity, self.model_id, api_key=self.api_key)
    
    async def generate_macro_summary(
        self,
        run_date: date,
        macro_context: Dict[str, Any],
        pipeline_run_id: UUID,
        model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate the macro + sector regime summary report using AnalystRole.
        """
        self._ensure_roles()
        model = model or self.model_id
        
        for attempt in range(self.max_retries + 1):
            try:
                if self._analyst:
                    # Use role-based AI
                    result = await self._analyst.analyze_global(
                        run_date=str(run_date),
                        signals_data=macro_context.get("etf_signals", []),
                    )
                    content = result.content
                else:
                    # Fallback to placeholder
                    content = self._placeholder_summary(macro_context, model)
                
                return {
                    "run_date": run_date,
                    "symbol": None,
                    "report_type": "macro_summary",
                    "content_md": content,
                    "model_used": model,
                    "identity_used": self.identity_key,
                    "input_context": _json_safe(macro_context),
                    "pipeline_run_id": pipeline_run_id,
                }
                
            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(f"Q2: Retry {attempt + 1}/{self.max_retries} for macro_summary: {e}")
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"Q2: Failed macro_summary after {self.max_retries + 1} attempts: {e}")
                    return None
        
        return None
    
    async def generate_batch_execution_plans(
        self,
        run_date: date,
        batch_symbols: List[str],
        batch_context: Dict[str, Any],
        global_context: str,
        pipeline_run_id: UUID,
        model: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Generate analysis for a batch of symbols using AnalystRole.
        Each symbol gets its own LLM call with global regime context.
        """
        self._ensure_roles()
        model = model or self.model_id
        
        records = []
        for symbol in batch_symbols:
            for attempt in range(self.max_retries + 1):
                try:
                    if self._analyst:
                        # Get symbol technical data from batch context
                        symbol_signals = batch_context.get("signals_by_symbol", {}).get(symbol, [])
                        historical_signals = batch_context.get("historical_signals_by_symbol", {}).get(symbol, [])
                        symbol_data_json = json.dumps({
                            "symbol": symbol,
                            "signals": symbol_signals,
                            "historical_signals": historical_signals,
                        }, indent=2, default=str)
                        
                        result = await self._analyst.analyze_symbol(
                            symbol_data_json=symbol_data_json,
                            global_context=global_context,
                        )
                        plan_content = result.content
                    else:
                        plan_content = self._placeholder_plan(symbol, batch_context, model)
                    
                    records.append({
                        "run_date": run_date,
                        "symbol": symbol,
                        "report_type": "symbol_execution_plan",
                        "content_md": plan_content,
                        "model_used": model,
                        "identity_used": self.identity_key,
                        "input_context": _json_safe({
                            "batch_symbols": batch_symbols,
                            "symbol": symbol,
                        }),
                        "pipeline_run_id": pipeline_run_id,
                    })
                    logger.info(f"Q2: Generated execution plan for {symbol}")
                    break  # Success, move to next symbol
                    
                except Exception as e:
                    if attempt < self.max_retries:
                        logger.warning(
                            f"Q2: Retry {attempt + 1}/{self.max_retries} for {symbol}: {e}"
                        )
                        await asyncio.sleep(2 ** attempt)
                    else:
                        logger.error(f"Q2: Failed {symbol} after {self.max_retries + 1} attempts: {e}")
        
        return records
    
    async def generate_portfolio_summary(
        self,
        run_date: date,
        global_report_md: str,
        symbol_plans: Dict[str, str],
        pipeline_run_id: UUID,
        model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate portfolio summary using SummarizerRole.
        Consolidates global report + all symbol plans into a final portfolio report.
        """
        self._ensure_roles()
        model = model or self.model_id
        
        for attempt in range(self.max_retries + 1):
            try:
                if self._summarizer:
                    result = await self._summarizer.summarize(
                        run_date=str(run_date),
                        global_report=global_report_md,
                        symbol_reports=symbol_plans,
                    )
                    content = result.content
                else:
                    content = f"# Portfolio Summary — {run_date}\n\n*Pending LLM integration*"
                
                return {
                    "run_date": run_date,
                    "symbol": None,
                    "report_type": "portfolio_summary",
                    "content_md": content,
                    "model_used": model,
                    "identity_used": self.identity_key,
                    "input_context": _json_safe({
                        "symbols": list(symbol_plans.keys()),
                        "has_global_context": bool(global_report_md),
                    }),
                    "pipeline_run_id": pipeline_run_id,
                }
                
            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(f"Q2: Retry {attempt + 1}/{self.max_retries} for portfolio_summary: {e}")
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"Q2: Failed portfolio_summary after {self.max_retries + 1} attempts: {e}")
                    return None
        
        return None
    
    # --- Placeholder methods (fallback when LLM not available) ---
    
    @staticmethod
    def _placeholder_summary(macro_context: Dict[str, Any], model: str) -> str:
        etf_signals = macro_context.get("etf_signals", [])
        report = f"# Market Macro & Sector Summary — {macro_context.get('run_date', 'N/A')}\n\n"
        report += f"## Macro Regime\n\nBased on {len(etf_signals)} ETF/index signals:\n\n"
        for sig in etf_signals:
            report += f"- **{sig.get('symbol')}**: {sig.get('signal', 'N/A').upper()} "
            report += f"(confidence: {sig.get('confidence', 0):.2f})\n"
        report += f"\n---\n*Generated by TraderCat Pipeline Q2 (model: {model})*\n"
        return report
    
    @staticmethod
    def _placeholder_plan(symbol: str, batch_context: Dict[str, Any], model: str) -> str:
        symbol_signals = batch_context.get("signals_by_symbol", {}).get(symbol, [])
        historical_signals = batch_context.get("historical_signals_by_symbol", {}).get(symbol, [])
        plan = f"# {symbol} Execution Plan — {batch_context.get('run_date', 'N/A')}\n\n"
        plan += "## Current Signals\n\n"
        for sig in symbol_signals:
            plan += f"- **{sig.get('strategy')}**: {sig.get('signal', 'N/A').upper()} "
            plan += f"(confidence: {sig.get('confidence', 0):.2f})\n"
        if historical_signals:
            plan += "\n## Historical Signals (Past 3 Trading Days)\n\n"
            for sig in historical_signals:
                plan += f"- [{sig.get('run_date')}] **{sig.get('strategy')}**: {sig.get('signal', 'N/A').upper()} "
                plan += f"(confidence: {sig.get('confidence', 0):.2f})\n"
        plan += f"\n---\n*Generated by TraderCat Pipeline Q2 (model: {model})*\n"
        return plan


async def generate_global_reports_q2(
    run_date: date,
    all_signals: List[Dict[str, Any]],
    pipeline_run_id: UUID,
    global_symbols: List[str],
    batch_size: int = 10,
    max_concurrency: int = 3,
    identity_key: str | None = None,
    api_key: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Q2: Generate all global reports using the 3-role AI infrastructure.
    
    Flow:
      1. Macro summary (global analysis) — one report
      2. Per-symbol execution plans (symbol analysis) — batched
      3. Portfolio summary (summary role) — consolidates everything
    """
    worker = GlobalReportWorker(identity_key=identity_key, api_key=api_key)
    all_records: List[Dict[str, Any]] = []
    
    # --- Build contexts ---
    etf_signals = [s for s in all_signals if s["symbol"] in global_symbols]
    macro_context = {
        "run_date": str(run_date),
        "etf_signals": etf_signals,
    }
    
    # --- Fetch past 3 trading days' signals for historical context ---
    historical_signals_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    try:
        past_dates: List[date] = []
        d = run_date
        for _ in range(3):
            d = get_previous_market_day(d)
            past_dates.append(d)
        
        from tradercat.database import AsyncSessionLocal
        from tradercat.models import SignalRecord
        
        async with AsyncSessionLocal() as db:
            stmt = (
                select(SignalRecord)
                .where(SignalRecord.run_date.in_(past_dates))
                .order_by(SignalRecord.run_date.desc())
            )
            result = await db.execute(stmt)
            for row in result.scalars().all():
                historical_signals_by_symbol.setdefault(row.symbol, []).append({
                    "run_date": str(row.run_date),
                    "symbol": row.symbol,
                    "strategy": row.strategy,
                    "signal": row.signal,
                    "confidence": row.confidence,
                    "reason": row.reason,
                    "details": row.details,
                })
        
        total_hist = sum(len(v) for v in historical_signals_by_symbol.values())
        logger.info(
            f"Q2: Loaded {total_hist} historical signals from past 3 trading days "
            f"({', '.join(str(d) for d in past_dates)}) for {len(historical_signals_by_symbol)} symbols"
        )
    except Exception as e:
        logger.warning(f"Q2: Failed to load historical signals, continuing without them: {e}")
    
    signals_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    all_plan_symbols = []
    # Keep only QQQ/SPY from global symbols; exclude other global ETFs from Step 2
    keep_global = {"QQQ", "SPY"}
    excluded_global = set(global_symbols) - keep_global
    for sig in all_signals:
        sym = sig["symbol"]
        signals_by_symbol.setdefault(sym, []).append(sig)
        if sym not in all_plan_symbols and sym not in excluded_global:
            all_plan_symbols.append(sym)
    
    # --- Step 1: Macro summary ---
    summary_record = await worker.generate_macro_summary(
        run_date=run_date,
        macro_context=macro_context,
        pipeline_run_id=pipeline_run_id,
    )
    
    global_context_md = ""
    if summary_record:
        all_records.append(summary_record)
        global_context_md = summary_record["content_md"]
    
    # --- Step 2: Batched symbol execution plans ---
    batches = [
        all_plan_symbols[i:i + batch_size]
        for i in range(0, len(all_plan_symbols), batch_size)
    ]
    
    batch_queue = asyncio.Queue()
    for batch in batches:
        await batch_queue.put(batch)
    
    batch_results: List[Dict[str, Any]] = []
    
    async def batch_worker_fn():
        results = []
        w = GlobalReportWorker(identity_key=identity_key, api_key=api_key)
        while True:
            try:
                batch_symbols = batch_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                batch_context = {
                    "run_date": str(run_date),
                    "signals_by_symbol": {
                        sym: signals_by_symbol.get(sym, [])
                        for sym in batch_symbols
                    },
                    "historical_signals_by_symbol": {
                        sym: historical_signals_by_symbol.get(sym, [])
                        for sym in batch_symbols
                    },
                }
                records = await w.generate_batch_execution_plans(
                    run_date=run_date,
                    batch_symbols=batch_symbols,
                    batch_context=batch_context,
                    global_context=global_context_md,
                    pipeline_run_id=pipeline_run_id,
                )
                results.extend(records)
            finally:
                batch_queue.task_done()
        return results
    
    batch_workers = [
        asyncio.create_task(batch_worker_fn())
        for _ in range(min(max_concurrency, len(batches) or 1))
    ]
    
    batch_worker_results = await asyncio.gather(*batch_workers)
    
    symbol_plans: Dict[str, str] = {}
    for result_list in batch_worker_results:
        all_records.extend(result_list)
        for rec in result_list:
            if rec.get("symbol"):
                symbol_plans[rec["symbol"]] = rec["content_md"]
    
    # --- Step 3: Portfolio Summary ---
    if symbol_plans:
        portfolio_record = await worker.generate_portfolio_summary(
            run_date=run_date,
            global_report_md=global_context_md,
            symbol_plans=symbol_plans,
            pipeline_run_id=pipeline_run_id,
        )
        if portfolio_record:
            all_records.append(portfolio_record)
    
    logger.info(
        f"Q2 complete: 1 macro_summary + {len(symbol_plans)} execution plans "
        f"+ 1 portfolio_summary from {len(batches)} batches"
    )
    return all_records
