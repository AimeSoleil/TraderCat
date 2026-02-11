"""Signal generation worker for pipeline."""
import asyncio
from datetime import datetime, date
from typing import List, Optional, Dict, Any
from uuid import UUID

from tradercat.logger.logger import get_logger
from tradercat.core.bot import TraderBot
from tradercat.core.data.openbb_provider import OpenBBProvider
from tradercat.models import SignalScope

logger = get_logger(__name__)


class SignalWorker:
    """Worker for processing symbols and generating signals."""
    
    def __init__(
        self,
        data_provider: Optional[OpenBBProvider] = None,
        max_retries: int = 1
    ):
        """
        Initialize signal worker.
        
        Args:
            data_provider: Data provider instance
            max_retries: Number of retries per symbol on failure
        """
        self.data_provider = data_provider or OpenBBProvider()
        self.max_retries = max_retries
    
    async def process_symbol(
        self,
        symbol: str,
        run_date: date,
        scope: SignalScope,
        pipeline_run_id: UUID,
        user_strategy_overrides: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Process a single symbol and generate signals.
        
        Args:
            symbol: Stock symbol to process
            run_date: Date of the pipeline run
            scope: Signal scope (GLOBAL or USER)
            pipeline_run_id: Pipeline run ID
            user_strategy_overrides: Optional user-specific strategy parameters
            
        Returns:
            List of signal records ready for database insertion
        """
        for attempt in range(self.max_retries + 1):
            try:
                # Create bot instance with optional user overrides
                bot = TraderBot(
                    data_provider=self.data_provider,
                    user_strategy_overrides=user_strategy_overrides
                )
                
                # Process symbol
                signals = await bot.process_symbol(symbol)
                
                # Convert to database records
                signal_records = []
                for signal in signals:
                    signal_records.append({
                        "run_date": run_date,
                        "symbol": symbol,
                        "strategy": signal.strategy,
                        "signal": signal.signal,
                        "confidence": signal.confidence,
                        "reason": signal.reason,
                        "details": signal.details,
                        "scope": scope,
                        "pipeline_run_id": pipeline_run_id,
                    })
                
                logger.info(f"Generated {len(signal_records)} signals for {symbol}")
                return signal_records
                
            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(f"Retry {attempt + 1}/{self.max_retries} for {symbol}: {e}")
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logger.error(f"Failed to process {symbol} after {self.max_retries + 1} attempts: {e}")
                    return []
        
        return []


async def process_symbols_concurrent(
    symbols: List[str],
    run_date: date,
    scope: SignalScope,
    pipeline_run_id: UUID,
    max_concurrency: int = 5,
    user_strategy_overrides: Optional[Dict[str, Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """
    Process multiple symbols concurrently using a queue and workers.
    
    Args:
        symbols: List of symbols to process
        run_date: Date of the pipeline run
        scope: Signal scope (GLOBAL or USER)
        pipeline_run_id: Pipeline run ID
        max_concurrency: Maximum number of concurrent workers
        user_strategy_overrides: Optional user-specific strategy parameters
        
    Returns:
        List of all signal records
    """
    queue = asyncio.Queue()
    results = []
    
    # Enqueue all symbols
    for symbol in symbols:
        await queue.put(symbol)
    
    # Worker coroutine
    async def worker():
        worker_results = []
        signal_worker = SignalWorker()
        
        while True:
            try:
                symbol = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            
            try:
                signal_records = await signal_worker.process_symbol(
                    symbol=symbol,
                    run_date=run_date,
                    scope=scope,
                    pipeline_run_id=pipeline_run_id,
                    user_strategy_overrides=user_strategy_overrides
                )
                worker_results.extend(signal_records)
            finally:
                queue.task_done()
        
        return worker_results
    
    # Spawn workers
    workers = [asyncio.create_task(worker()) for _ in range(min(max_concurrency, len(symbols)))]
    
    # Wait for all workers to complete
    worker_results = await asyncio.gather(*workers)
    
    # Flatten results
    for result_list in worker_results:
        results.extend(result_list)
    
    return results
