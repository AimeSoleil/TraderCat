"""Global report generation worker for pipeline (Q2) — role-based AI.

Q2 uses the role-based AI infrastructure:
  Phase 2a: Global Analysis — Macro regime + sector rotation (AnalystRole)
  Phase 2b: Symbol Analysis — Per-symbol options execution plans (AnalystRole)

Personalized portfolio summaries are generated per-user in Q3 (user_report_worker)
using SummarizerRole with each user's preferred persona and watchlist.

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

        logger.info(f"Q2: Generating macro summary for {run_date} with identity '{self.identity_key}' and model '{model}'")
        
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
        Generate analysis for a batch of symbols in a SINGLE LLM call.
        All symbols in the batch are sent together so the model can
        cross-reference correlations and produce a more coherent set of plans.
        """
        self._ensure_roles()
        model = model or self.model_id
        
        # --- Build combined symbol data for the entire batch ---
        batch_data = []
        for symbol in batch_symbols:
            symbol_signals = batch_context.get("signals_by_symbol", {}).get(symbol, [])
            historical_signals = batch_context.get("historical_signals_by_symbol", {}).get(symbol, [])
            batch_data.append({
                "symbol": symbol,
                "signals": symbol_signals,
                #"historical_signals": historical_signals,
            })
        
        combined_json = json.dumps(batch_data, indent=2, default=str)
        
        for attempt in range(self.max_retries + 1):
            try:
                if self._analyst:
                    result = await self._analyst.analyze_symbol(
                        symbol_data_json=combined_json,
                        global_context=global_context,
                    )
                    combined_content = result.content or ""
                    logger.info(
                        f"Q2: Batch LLM returned {len(combined_content)} chars "
                        f"for {len(batch_symbols)} symbols: {batch_symbols}"
                    )
                    if not combined_content.strip():
                        raise ValueError(
                            f"LLM returned empty content for batch {batch_symbols}"
                        )
                else:
                    # Fallback: generate placeholders for each symbol
                    parts = []
                    for symbol in batch_symbols:
                        parts.append(self._placeholder_plan(symbol, batch_context, model))
                    combined_content = "\n\n---\n\n".join(parts)
                
                # --- Split combined response into per-symbol records ---
                return self._split_batch_response(
                    combined_content=combined_content,
                    batch_symbols=batch_symbols,
                    run_date=run_date,
                    model=model,
                    pipeline_run_id=pipeline_run_id,
                )
                
            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(
                        f"Q2: Retry {attempt + 1}/{self.max_retries} for batch "
                        f"{batch_symbols}: {e}"
                    )
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(
                        f"Q2: Failed batch {batch_symbols} after "
                        f"{self.max_retries + 1} attempts: {e}"
                    )
        
        return []
    
    def _split_batch_response(
        self,
        combined_content: str,
        batch_symbols: List[str],
        run_date: date,
        model: str,
        pipeline_run_id: UUID,
    ) -> List[Dict[str, Any]]:
        """Split a multi-symbol LLM response into per-symbol DB records.
        
        Heuristic: look for '## {SYMBOL}' markdown headers to delimit
        each symbol's section. If a symbol header isn't found, the entire
        combined output is stored under the first symbol (graceful fallback).
        """
        import re
        
        records: List[Dict[str, Any]] = []
        
        # Build a regex that matches any of the batch symbols as a ## header
        # e.g. "## AAPL", "## AAPL —", "## AAPL -", "## AAPL:", etc.
        symbol_pattern = "|".join(re.escape(s) for s in batch_symbols)
        header_re = re.compile(
            rf"^(##\s+(?:{symbol_pattern})\b)",
            re.MULTILINE | re.IGNORECASE,
        )
        
        # Find all header positions
        headers = list(header_re.finditer(combined_content))
        
        if len(headers) >= 2:
            # Multiple headers found — split by position
            sections: Dict[str, str] = {}
            for i, match in enumerate(headers):
                # Extract symbol from "## SYMBOL ..."
                hdr_text = match.group(1)
                sym_match = re.search(rf"({symbol_pattern})", hdr_text, re.IGNORECASE)
                sym = sym_match.group(1).upper() if sym_match else batch_symbols[i] if i < len(batch_symbols) else None
                if not sym:
                    continue
                
                start = match.start()
                end = headers[i + 1].start() if i + 1 < len(headers) else len(combined_content)
                sections[sym] = combined_content[start:end].strip()
            
            for symbol in batch_symbols:
                content = sections.get(symbol, f"## {symbol}\n\n*No analysis produced for this symbol in batch.*")
                records.append({
                    "run_date": run_date,
                    "symbol": symbol,
                    "report_type": "symbol_execution_plan",
                    "content_md": content,
                    "model_used": model,
                    "identity_used": self.identity_key,
                    "input_context": _json_safe({
                        "batch_symbols": batch_symbols,
                        "symbol": symbol,
                    }),
                    "pipeline_run_id": pipeline_run_id,
                })
                logger.info(f"Q2: Generated execution plan for {symbol} (batch)")
        else:
            # Couldn't split — store entire response for each symbol with a note,
            # or if only 1 symbol, use it directly.
            if len(batch_symbols) == 1:
                records.append({
                    "run_date": run_date,
                    "symbol": batch_symbols[0],
                    "report_type": "symbol_execution_plan",
                    "content_md": combined_content,
                    "model_used": model,
                    "identity_used": self.identity_key,
                    "input_context": _json_safe({
                        "batch_symbols": batch_symbols,
                        "symbol": batch_symbols[0],
                    }),
                    "pipeline_run_id": pipeline_run_id,
                })
                logger.info(f"Q2: Generated execution plan for {batch_symbols[0]}")
            else:
                # Store combined content under each symbol with prefix
                for symbol in batch_symbols:
                    records.append({
                        "run_date": run_date,
                        "symbol": symbol,
                        "report_type": "symbol_execution_plan",
                        "content_md": combined_content,
                        "model_used": model,
                        "identity_used": self.identity_key,
                        "input_context": _json_safe({
                            "batch_symbols": batch_symbols,
                            "symbol": symbol,
                            "note": "batch_unsplit",
                        }),
                        "pipeline_run_id": pipeline_run_id,
                    })
                logger.warning(
                    f"Q2: Could not split batch response for {batch_symbols} — "
                    f"stored combined output under each symbol"
                )
        
        return records
    
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
    batch_size: int = 1,
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
                    "ohlcv": row.ohlcv,
                    "indicators": row.indicators,
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
    
    # NOTE: Portfolio summary removed from Q2 — personalized summaries
    # are generated per-user in Q3 (user_report_worker) using SummarizerRole.
    
    logger.info(
        f"Q2 complete: 1 macro_summary + {len(symbol_plans)} execution plans "
        f"from {len(batches)} batches"
    )
    return all_records
