"""Global report generation worker for pipeline (Q2).

Q2 generates two types of global reports:
1. macro_summary: One summary of macro + sector regime from ETF/index signals.
2. symbol_execution_plan: Per-batch execution plans (N symbols per LLM call).

These reports are stored in global_reports (no user_id).
"""
import asyncio
from datetime import date
from typing import List, Dict, Any, Optional
from uuid import UUID

from tradercat.logger.logger import get_logger
from tradercat.config import settings

logger = get_logger(__name__)


class GlobalReportWorker:
    """Worker for generating global LLM reports (Q2)."""
    
    def __init__(self, max_retries: int | None = None):
        self.max_retries = max_retries if max_retries is not None else settings.pipeline_llm_max_retries
    
    async def generate_macro_summary(
        self,
        run_date: date,
        macro_context: Dict[str, Any],
        pipeline_run_id: UUID,
        model: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate the macro + sector regime summary report.
        One per pipeline run. Input: aggregated ETF/index signals.
        """
        model = model or settings.default_llm_model
        
        for attempt in range(self.max_retries + 1):
            try:
                content = await self._call_llm_summary(macro_context, model)
                
                return {
                    "run_date": run_date,
                    "symbol": None,  # macro_summary is not symbol-specific
                    "report_type": "macro_summary",
                    "content_md": content,
                    "model_used": model,
                    "persona_used": None,
                    "input_context": macro_context,
                    "pipeline_run_id": pipeline_run_id,
                }
                
            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(f"Q2: Retry {attempt + 1}/{self.max_retries} for macro_summary: {e}")
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"Q2: Failed to generate macro_summary after {self.max_retries + 1} attempts: {e}")
                    return None
        
        return None
    
    async def generate_batch_execution_plans(
        self,
        run_date: date,
        batch_symbols: List[str],
        batch_context: Dict[str, Any],
        pipeline_run_id: UUID,
        model: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Generate execution plans for a batch of symbols in a single LLM call.
        Returns one record per symbol in the batch.
        """
        model = model or settings.default_llm_model
        
        for attempt in range(self.max_retries + 1):
            try:
                # Single LLM call produces plans for all symbols in batch
                plans = await self._call_llm_batch_plans(batch_symbols, batch_context, model)
                
                records = []
                for symbol, plan_content in plans.items():
                    records.append({
                        "run_date": run_date,
                        "symbol": symbol,
                        "report_type": "symbol_execution_plan",
                        "content_md": plan_content,
                        "model_used": model,
                        "persona_used": None,
                        "input_context": {
                            "batch_symbols": batch_symbols,
                            "symbol": symbol,
                        },
                        "pipeline_run_id": pipeline_run_id,
                    })
                
                logger.info(f"Q2: Generated execution plans for batch: {batch_symbols}")
                return records
                
            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(
                        f"Q2: Retry {attempt + 1}/{self.max_retries} for batch {batch_symbols[:3]}...: {e}"
                    )
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(
                        f"Q2: Failed batch {batch_symbols} after {self.max_retries + 1} attempts: {e}"
                    )
                    return []
        
        return []
    
    async def _call_llm_summary(
        self,
        macro_context: Dict[str, Any],
        model: str,
    ) -> str:
        """
        Call LLM to generate macro summary.
        
        TODO: Integrate with tradercat.ai infrastructure.
        """
        # Placeholder - will be replaced with actual LLM call
        etf_signals = macro_context.get("etf_signals", [])
        
        report = f"""# Market Macro & Sector Summary - {macro_context.get('run_date', 'N/A')}

## Macro Regime

Based on analysis of {len(etf_signals)} ETF/index signals:

"""
        for sig in etf_signals:
            report += f"- **{sig.get('symbol')}** ({sig.get('strategy')}): {sig.get('signal', 'N/A').upper()} "
            report += f"(confidence: {sig.get('confidence', 0):.2f})\n"
        
        report += """
## Sector Rotation

*Analysis pending LLM integration*

## Risk Assessment

*Analysis pending LLM integration*

---
*Generated by TraderCat Pipeline Q2 (model: """ + model + ")*\n"
        
        return report
    
    async def _call_llm_batch_plans(
        self,
        symbols: List[str],
        batch_context: Dict[str, Any],
        model: str,
    ) -> Dict[str, str]:
        """
        Call LLM once to generate execution plans for all symbols in the batch.
        Returns a dict mapping symbol → plan markdown.
        
        TODO: Integrate with tradercat.ai infrastructure.
        """
        # Placeholder - will be replaced with actual LLM call
        plans = {}
        for symbol in symbols:
            symbol_signals = batch_context.get("signals_by_symbol", {}).get(symbol, [])
            
            plan = f"""# {symbol} Execution Plan - {batch_context.get('run_date', 'N/A')}

## Signal Summary

"""
            for sig in symbol_signals:
                plan += f"- **{sig.get('strategy')}**: {sig.get('signal', 'N/A').upper()} "
                plan += f"(confidence: {sig.get('confidence', 0):.2f})\n"
                if sig.get('reason'):
                    plan += f"  - {sig['reason']}\n"
            
            plan += """
## Recommended Action

*Pending LLM integration*

## Risk Parameters

*Pending LLM integration*

---
*Generated by TraderCat Pipeline Q2 (model: """ + model + ")*\n"
            
            plans[symbol] = plan
        
        return plans


async def generate_global_reports_q2(
    run_date: date,
    all_signals: List[Dict[str, Any]],
    pipeline_run_id: UUID,
    global_symbols: List[str],
    batch_size: int = 10,
    max_concurrency: int = 3,
) -> List[Dict[str, Any]]:
    """
    Q2: Generate all global reports.
    
    1. Generate one macro_summary from ETF/index signals.
    2. Batch all symbols and generate execution plans concurrently.
    
    Both run in parallel since they don't depend on each other.
    """
    worker = GlobalReportWorker()
    all_records: List[Dict[str, Any]] = []
    
    # --- Build contexts ---
    # Macro context: signals from global_symbols (ETFs/indices)
    etf_signals = [
        s for s in all_signals
        if s["symbol"] in global_symbols
    ]
    macro_context = {
        "run_date": str(run_date),
        "etf_signals": etf_signals,
    }
    
    # Signals grouped by symbol for execution plans
    signals_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    all_plan_symbols = []
    for sig in all_signals:
        sym = sig["symbol"]
        signals_by_symbol.setdefault(sym, []).append(sig)
        if sym not in all_plan_symbols:
            all_plan_symbols.append(sym)
    
    # --- Task 1: Macro summary (async) ---
    summary_task = asyncio.create_task(
        worker.generate_macro_summary(
            run_date=run_date,
            macro_context=macro_context,
            pipeline_run_id=pipeline_run_id,
        )
    )
    
    # --- Task 2: Batched execution plans (concurrent) ---
    batches = [
        all_plan_symbols[i:i + batch_size]
        for i in range(0, len(all_plan_symbols), batch_size)
    ]
    
    batch_queue = asyncio.Queue()
    for batch in batches:
        await batch_queue.put(batch)
    
    batch_results: List[Dict[str, Any]] = []
    
    async def batch_worker():
        results = []
        w = GlobalReportWorker()
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
                }
                records = await w.generate_batch_execution_plans(
                    run_date=run_date,
                    batch_symbols=batch_symbols,
                    batch_context=batch_context,
                    pipeline_run_id=pipeline_run_id,
                )
                results.extend(records)
            finally:
                batch_queue.task_done()
        return results
    
    batch_workers = [
        asyncio.create_task(batch_worker())
        for _ in range(min(max_concurrency, len(batches) or 1))
    ]
    
    # --- Wait for both summary + batch plans ---
    summary_record, *batch_worker_results = await asyncio.gather(
        summary_task, *batch_workers
    )
    
    if summary_record:
        all_records.append(summary_record)
    
    for result_list in batch_worker_results:
        all_records.extend(result_list)
    
    logger.info(
        f"Q2 complete: 1 macro_summary + {len(all_records) - (1 if summary_record else 0)} "
        f"execution plans from {len(batches)} batches"
    )
    return all_records
