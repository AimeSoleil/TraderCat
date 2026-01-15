import asyncio
import traceback
import os
from datetime import datetime
from typing import List, Dict

from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

class SessionRunner:
    """
    Encapsulates the core trading loop execution logic.
    Handles strategy execution, result collection, and reporting.
    """

    def __init__(self, executor, discord_notifier, drive_storage):
        self.executor = executor
        self.notifier = discord_notifier
        self.drive_storage = drive_storage

    async def run_session(self, symbols: List[str], max_concurrency: int = 5, stagger_sec: int = 2, scope: str = "all"):
        """
        Main orchestration method for a trading run.
        """
        # Lazy import to avoid circular dependencies or startup lag
        from tradercat.bot import TraderBot

        start_time = datetime.now()
        bot = TraderBot(executor=self.executor)
        all_results = []
        logger.info(f"Session Scope: {scope}")

        # 1. Run Portfolio Strategies
        if scope in ["all", "portfolio"]:
            try:
                portfolio_signals = await bot.process_portfolio()
                if portfolio_signals:
                    all_results.append({"symbol": "PORTFOLIO", "signals": portfolio_signals})
            except Exception as e:
                logger.error(f"Error in portfolio strategies: {e}")
                logger.error(traceback.format_exc())
        else:
            logger.info("Skipping Portfolio Strategies per scope.")

        # 2. Run Single-Asset Strategies
        if scope in ["all", "single"]:
            semaphore = asyncio.Semaphore(max_concurrency)

            async def worker(symbol):
                async with semaphore:
                    # Stagger requests to avoid API rate limits
                    await asyncio.sleep(stagger_sec * (symbols.index(symbol) % max_concurrency)) 
                    try:
                        signals = await bot.process_symbol(symbol)
                        if signals:
                            return {"symbol": symbol, "signals": signals}
                    except Exception as e:
                        logger.error(f"Error processing {symbol}: {e}")
                    return None

            if symbols:
                tasks = [worker(sym) for sym in symbols]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for res in results:
                    if isinstance(res, dict):
                        all_results.append(res)
        else:
            logger.info("Skipping Single-Asset Strategies per scope.")

        # 3. Reporting
        if all_results:
            self._save_signals_to_csv(all_results, scope)
            await self._send_discord_summary(all_results)
        else:
            logger.info("No signals generated this session.")

        duration = datetime.now() - start_time
        logger.info(f"✅ Session finished in {duration.total_seconds():.2f}s")

    def _save_signals_to_csv(self, all_signals: List[Dict], scope: str):
        """Internal helper: Exports collected signals to CSV and uploads to Drive."""
        import pandas as pd # Lazy import

        rows = []
        for entry in all_signals:
            for signal in entry["signals"]:
                rows.append({
                    "Close_Date": getattr(signal, "date", datetime.now().date()),
                    "Symbol": getattr(signal, "symbol", entry["symbol"]),
                    "Strategy": getattr(signal, "strategy", "Unknown"),
                    "Signal": getattr(signal, "signal", "Unknown"),
                    "Confidence": getattr(signal, "confidence", 0),
                    "Reason": getattr(signal, "reason", ""),
                    "Details": getattr(signal, "details", "")
                })
        
        if not rows: return

        df = pd.DataFrame(rows)
        filename = f"results/trade_signals_{scope}_{datetime.now().strftime('%Y%m%d%H%M')}.csv"
        os.makedirs("results", exist_ok=True)
        df.to