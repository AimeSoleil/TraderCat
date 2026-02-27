"""Signal generation worker for pipeline (Q1).

Q1 processes all unique symbols (global + user watchlist) in a single pass.
Scope is assigned by metadata: symbols in global_symbols list → 'global', others → 'user'.
"""
import asyncio
from datetime import datetime, date
from typing import List, Optional, Dict, Any, Set
from uuid import UUID

from tradercat.logger import get_logger
from tradercat.core.bot import TraderBot
from tradercat.core.data.openbb_provider import OpenBBProvider
from tradercat.models import SignalScope
from tradercat.config import settings

logger = get_logger(__name__)

class SignalWorker:
    """Worker for processing symbols and generating signals."""
    
    def __init__(
        self,
        data_provider: Optional[OpenBBProvider] = None,
        max_retries: int = 1,
        strategy_configs: Optional[List[Dict[str, Any]]] = None,
    ):
        self.data_provider = data_provider or OpenBBProvider()
        self.max_retries = max_retries
        self.strategy_configs = strategy_configs
        self._global_symbols: Set[str] = set(settings.global_symbols)
    
    def _resolve_scope(self, symbol: str) -> str:
        """Resolve scope based on whether symbol is in the global list."""
        return SignalScope.GLOBAL.value if symbol in self._global_symbols else SignalScope.USER.value
    
    async def process_symbol(
        self,
        symbol: str,
        run_date: date,
        pipeline_run_id: UUID,
    ) -> List[Dict[str, Any]]:
        """
        Process a single symbol and generate signals.
        Scope is automatically resolved from the global symbols list.
        """
        scope = self._resolve_scope(symbol)
        
        for attempt in range(self.max_retries + 1):
            try:
                bot = TraderBot(
                    data_provider=self.data_provider,
                    strategy_configs=self.strategy_configs,
                )
                
                signals = await bot.process_symbol(symbol)
                
                signal_records = []
                for signal in signals:
                    signal_records.append({
                        "run_date": run_date,
                        "symbol": symbol,
                        "strategy": signal.strategy,
                        "signal": signal.signal,
                        "confidence": signal.confidence,
                        "reason": signal.reason,
                        "ohlcv": signal.ohlcv,
                        "indicators": signal.indicators,
                        "scope": scope,
                        "pipeline_run_id": pipeline_run_id,
                    })
                
                logger.info(f"Q1: Generated {len(signal_records)} signals for {symbol} (scope={scope})")
                return signal_records
                
            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(f"Q1: Retry {attempt + 1}/{self.max_retries} for {symbol}: {e}")
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"Q1: Failed to process {symbol} after {self.max_retries + 1} attempts: {e}")
                    return []
        
        return []

async def process_symbols_q1(
    symbols: List[str],
    run_date: date,
    pipeline_run_id: UUID,
    max_concurrency: int = 5,
    strategy_configs: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Q1: Process all unique symbols concurrently.
    
    Symbols are deduped before this call by the orchestrator.
    Scope is auto-resolved per symbol (global vs user).
    """
    if not symbols:
        return []
    
    queue = asyncio.Queue()
    results = []
    
    for symbol in symbols:
        await queue.put(symbol)
    
    async def worker():
        worker_results = []
        signal_worker = SignalWorker(strategy_configs=strategy_configs)
        
        while True:
            try:
                symbol = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            
            try:
                signal_records = await signal_worker.process_symbol(
                    symbol=symbol,
                    run_date=run_date,
                    pipeline_run_id=pipeline_run_id,
                )
                worker_results.extend(signal_records)
            finally:
                queue.task_done()
        
        return worker_results
    
    workers = [asyncio.create_task(worker()) for _ in range(min(max_concurrency, len(symbols)))]
    worker_results = await asyncio.gather(*workers)
    
    for result_list in worker_results:
        results.extend(result_list)
    
    logger.info(f"Q1 complete: {len(results)} total signals from {len(symbols)} symbols")
    return results
