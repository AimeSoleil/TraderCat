"""Execution plan worker for pipeline P3 — OptionsStrategistRole.

P3 produces per-symbol options execution plans for:
  - All user watchlist symbols
  - QQQ, SPY, IWM (always included)

Uses OptionsStrategistRole with options_strategist identity.
Processes symbols in batches for efficiency with concurrent workers.

Token optimization:
  - Sends compressed regime context (Section 4 only) instead of full P2 markdown.
  - OHLCV de-duplicated and compressed per symbol.
  - Historical signals compressed to (date, strategy, signal, confidence).
"""
import asyncio
import json
import re
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


def _extract_verdict(content: str) -> Optional[str]:
    """Best-effort extraction of verdict from a single-symbol report section."""
    m = re.search(r"\*\*Direction\*\*:\s*(\S+)", content, re.IGNORECASE)
    if m:
        raw = m.group(1).strip().lower()
        mapping = {"long": "buy", "short": "sell", "neutral": "hold"}
        return mapping.get(raw, raw)
    return None


def _extract_quality(content: str) -> Optional[str]:
    """Best-effort extraction of setup quality grade."""
    m = re.search(r"\*\*Setup Quality\*\*:\s*(\S+)", content, re.IGNORECASE)
    if m:
        return m.group(1).strip()[:10]
    return None


class ExecutionPlanWorker:
    """Worker for generating per-symbol execution plans (P3)."""

    # Fixed identity for P3 — always "options_strategist"
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
            logger.warning(f"P3: Failed to init LLM provider: {e}. Will use fallback.")
            self._provider = None
            return
        identity = IdentityRole(self._P3_IDENTITY)
        self._strategist = OptionsStrategistRole(
            self._provider, identity, self.model_id, api_key=self.api_key
        )

    async def generate_batch(
        self,
        run_date: date,
        batch_symbols: List[str],
        signals_by_symbol: Dict[str, List[Dict[str, Any]]],
        historical_by_symbol: Dict[str, List[Dict[str, Any]]],
        regime_context_md: str,
        pipeline_run_id: UUID,
    ) -> List[Dict[str, Any]]:
        """
        Generate execution plans for a batch of symbols in a SINGLE LLM call.

        Returns list of dicts ready for DB insert/upsert.
        """
        self._ensure_roles()

        # Build token-efficient payload
        combined_json = build_batch_payload(
            batch_symbols=batch_symbols,
            signals_by_symbol={s: signals_by_symbol.get(s, []) for s in batch_symbols},
            historical_by_symbol={s: historical_by_symbol.get(s, []) for s in batch_symbols},
        )

        # Compress regime context to downstream filters only
        compressed_context = extract_downstream_filters(regime_context_md)

        for attempt in range(self.max_retries + 1):
            try:
                if self._strategist:
                    result = await self._strategist.analyze_batch(
                        symbol_data_json=combined_json,
                        global_context=compressed_context,
                    )
                    combined_content = result.content or ""
                    logger.info(
                        f"P3: Batch LLM returned {len(combined_content)} chars "
                        f"for {len(batch_symbols)} symbols: {batch_symbols}"
                    )
                    if not combined_content.strip():
                        raise ValueError(f"LLM returned empty content for batch {batch_symbols}")
                else:
                    parts = [self._placeholder(s, signals_by_symbol.get(s, [])) for s in batch_symbols]
                    combined_content = "\n\n---\n\n".join(parts)

                return self._split_batch_response(
                    combined_content=combined_content,
                    batch_symbols=batch_symbols,
                    run_date=run_date,
                    pipeline_run_id=pipeline_run_id,
                )

            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(f"P3: Retry {attempt + 1}/{self.max_retries} for batch {batch_symbols}: {e}")
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"P3: Failed batch {batch_symbols} after {self.max_retries + 1} attempts: {e}")

        return []

    def _split_batch_response(
        self,
        combined_content: str,
        batch_symbols: List[str],
        run_date: date,
        pipeline_run_id: UUID,
    ) -> List[Dict[str, Any]]:
        """Split multi-symbol LLM response into per-symbol DB records."""
        records: List[Dict[str, Any]] = []

        # Build regex for ## SYMBOL headers
        symbol_pattern = "|".join(re.escape(s) for s in batch_symbols)
        header_re = re.compile(
            rf"^(##\s+(?:{symbol_pattern})\b)",
            re.MULTILINE | re.IGNORECASE,
        )

        headers = list(header_re.finditer(combined_content))

        if len(headers) >= 2:
            sections: Dict[str, str] = {}
            for i, match in enumerate(headers):
                hdr_text = match.group(1)
                sym_match = re.search(rf"({symbol_pattern})", hdr_text, re.IGNORECASE)
                sym = sym_match.group(1).upper() if sym_match else batch_symbols[i] if i < len(batch_symbols) else None
                if not sym:
                    continue
                start = match.start()
                end = headers[i + 1].start() if i + 1 < len(headers) else len(combined_content)
                sections[sym] = combined_content[start:end].strip()

            for symbol in batch_symbols:
                content = sections.get(symbol, f"## {symbol}\n\n*No analysis produced.*")
                records.append({
                    "run_date": run_date,
                    "symbol": symbol,
                    "verdict": _extract_verdict(content),
                    "setup_quality": _extract_quality(content),
                    "content_md": content,
                    "model_used": self.model_id,
                    "identity_used": self._P3_IDENTITY,
                    "input_context": _json_safe({"batch_symbols": batch_symbols, "symbol": symbol}),
                    "pipeline_run_id": pipeline_run_id,
                })
        elif len(batch_symbols) == 1:
            records.append({
                "run_date": run_date,
                "symbol": batch_symbols[0],
                "verdict": _extract_verdict(combined_content),
                "setup_quality": _extract_quality(combined_content),
                "content_md": combined_content,
                "model_used": self.model_id,
                "identity_used": self._P3_IDENTITY,
                "input_context": _json_safe({"batch_symbols": batch_symbols, "symbol": batch_symbols[0]}),
                "pipeline_run_id": pipeline_run_id,
            })
        else:
            for symbol in batch_symbols:
                records.append({
                    "run_date": run_date,
                    "symbol": symbol,
                    "verdict": None,
                    "setup_quality": None,
                    "content_md": combined_content,
                    "model_used": self.model_id,
                    "identity_used": self._P3_IDENTITY,
                    "input_context": _json_safe({"batch_symbols": batch_symbols, "symbol": symbol, "note": "batch_unsplit"}),
                    "pipeline_run_id": pipeline_run_id,
                })
            logger.warning(f"P3: Could not split batch response for {batch_symbols}")

        return records

    @staticmethod
    def _placeholder(symbol: str, signals: List[Dict[str, Any]]) -> str:
        plan = f"## {symbol} — Analysis Report\n\n"
        plan += "### Signal Assessment\n"
        plan += "- **Direction**: NEUTRAL\n"
        plan += "- **Setup Quality**: C\n\n"
        for sig in signals:
            plan += f"- **{sig.get('strategy')}**: {sig.get('signal', 'N/A').upper()} "
            plan += f"(confidence: {sig.get('confidence', 0):.2f})\n"
        plan += "\n---\n*Placeholder — LLM not available*\n"
        return plan


async def generate_execution_plans_p3(
    run_date: date,
    all_signals: List[Dict[str, Any]],
    pipeline_run_id: UUID,
    global_symbols: List[str],
    regime_context_md: str,
    batch_size: int = 5,
    max_concurrency: int = 3,
    api_key: str | None = None,
) -> List[Dict[str, Any]]:
    """
    P3 entry point: generate execution plans for all plan-eligible symbols.

    Plan-eligible = {QQQ, SPY, IWM} ∪ all watchlist symbols.
    Excludes sector ETFs that are only for macro analysis.
    """
    # --- Fetch historical signals (past 1 trading day) ---
    historical_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    try:
        from tradercat.pipeline.holidays import get_previous_market_day
        past_dates: List[date] = []
        d = run_date
        for _ in range(1):
            d = get_previous_market_day(d)
            past_dates.append(d)

        from tradercat.database import AsyncSessionLocal
        from tradercat.models import SignalRecord
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
                })

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

    logger.info(f"P3: {len(plan_symbols)} symbols for execution plans (excluded {len(excluded_global)} macro-only ETFs)")

    # --- Batch and process ---
    batches = [plan_symbols[i:i + batch_size] for i in range(0, len(plan_symbols), batch_size)]

    batch_queue: asyncio.Queue = asyncio.Queue()
    for batch in batches:
        await batch_queue.put(batch)

    all_records: List[Dict[str, Any]] = []

    async def batch_worker_fn():
        results = []
        worker = ExecutionPlanWorker(api_key=api_key)
        while True:
            try:
                batch_symbols = batch_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                records = await worker.generate_batch(
                    run_date=run_date,
                    batch_symbols=batch_symbols,
                    signals_by_symbol=signals_by_symbol,
                    historical_by_symbol=historical_by_symbol,
                    regime_context_md=regime_context_md,
                    pipeline_run_id=pipeline_run_id,
                )
                results.extend(records)
            finally:
                batch_queue.task_done()
        return results

    workers = [
        asyncio.create_task(batch_worker_fn())
        for _ in range(min(max_concurrency, len(batches) or 1))
    ]
    worker_results = await asyncio.gather(*workers)

    for result_list in worker_results:
        all_records.extend(result_list)

    logger.info(f"P3 complete: {len(all_records)} execution plans from {len(batches)} batches")
    return all_records
