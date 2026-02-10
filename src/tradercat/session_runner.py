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
        
        if not rows: 
            logger.info("No signal rows to save; skipping CSV export.")
            return

        df = pd.DataFrame(rows)
        timestamp = datetime.now().strftime('%Y%m%d%H%M')
        os.makedirs("results", exist_ok=True)

        # Save full signals CSV
        filename = f"results/trade_signals_{scope}_{timestamp}.csv"
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        logger.info(f"📄 Signals CSV created: {filename}")

        if self.drive_storage:
            self.drive_storage.upload_file(filename)

        # Save actionable CSV: keep symbols that have at least one non-hold signal
        # Always keep SPY and QQQ regardless of signal status
        always_keep = {"SPY", "QQQ"}
        all_hold_symbols = df.groupby("Symbol").filter(
            lambda g: (g["Signal"].str.lower() == "hold").all()
        )["Symbol"].unique()
        actionable_df = df[~df["Symbol"].isin(all_hold_symbols) | df["Symbol"].isin(always_keep)]

        if not actionable_df.empty:
            actionable_filename = f"results/trade_signals_actionable_{scope}_{timestamp}.csv"
            actionable_df.to_csv(actionable_filename, index=False, encoding='utf-8-sig')
            logger.info(f"📄 Actionable CSV created: {actionable_filename} ({actionable_df['Symbol'].nunique()} symbols)")

            if self.drive_storage:
                self.drive_storage.upload_file(actionable_filename)
        else:
            logger.info("All symbols are hold-only; skipping actionable CSV export.")

    async def _send_discord_summary(self, all_signals: List[Dict]):
        """Internal helper: Formats and sends a summary to Discord."""
        if not self.notifier:
            return

        today_str = datetime.today().strftime("%Y-%m-%d")
        message_lines = [f"** 💸 Daily [{today_str}] Trade Signals Summary: **"]
        
        has_signals = False
        for entry in all_signals:
            for s in entry["signals"]:
                if s.signal in ("buy", "sell", "rebalance"):
                    has_signals = True
                    line = (f"* **{entry['symbol']}**: {s.signal.upper()} | "
                            f"Strat: {s.strategy} | Conf: {s.confidence:.2f} | "
                            f"Reason: {s.reason} *")
                    message_lines.append(line)

        if not has_signals:
            message_lines.append("No actionable BUY/SELL/REBALANCE signals generated.")

        full_message = "\n".join(message_lines)
        logger.info(f"🔔 Sending Discord Notification:\n{full_message}")
        
        try:
            await self.notifier.send(full_message)
        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}")