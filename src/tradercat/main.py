import asyncio
import argparse
import os
import sys
from datetime import datetime
from typing import List, Dict
import yaml

# 仅保留轻量级的 logger, 以避免启动时的性能开销
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

DEFAULT_SYMBOLS_STR = os.environ.get("ENV_SYMBOLS")

# --- Helper Functions ---

def load_symbols(args) -> List[str]:
    """Determines the source of symbols and loads them."""
    symbols = []
    if args.symbols:
        logger.info(f"Symbols from CLI: {args.symbols}")
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.symbols_file:
        logger.info(f"Loading symbols from file: {args.symbols_file}")
        ext = os.path.splitext(args.symbols_file)[1].lower()
        with open(args.symbols_file, "r") as f:
            if ext in [".yaml", ".yml"]:
                data = yaml.safe_load(f)
                symbols = [s.strip().upper() for s in data.get("symbols", [])]
            else:
                symbols = [line.strip().upper() for line in f if line.strip()]
    else:
        logger.info("Loading symbols from ENV_SYMBOLS.")
        if DEFAULT_SYMBOLS_STR:
            symbols = [s.strip().upper() for s in DEFAULT_SYMBOLS_STR.split(",") if s.strip()]
    
    return list(dict.fromkeys(symbols))

def save_signals_to_csv(all_signals: List[Dict], drive_storage, scope: str = "all"):
    """Exports collected signals to a CSV file and uploads to Drive."""
    # ⚡️ 延迟导入 Pandas，因为它启动很慢
    import pandas as pd

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
        return

    df = pd.DataFrame(rows)
    filename = f"results/trade_signals_{scope}_{datetime.now().strftime('%Y%m%d%H%M')}.csv"
    
    # Ensure directory exists
    os.makedirs("results", exist_ok=True)
    
    df.to_csv(filename, index=False, encoding='utf-8-sig')
    logger.info(f"📄 Signals CSV created: {filename}")

    drive_storage.upload_file(filename)

async def send_discord_summary(discord_notifier, all_signals: List[Dict]):
    """Formats and sends a summary to Discord."""
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
        await discord_notifier.send(full_message)
    except Exception as e:
        logger.error(f"Failed to send Discord notification: {e}")

# --- Core Logic ---

async def run_trading_session(symbols: List[str], 
                              executor, 
                              discord_notifier, 
                              drive_storage, 
                              max_concurrency: int = 5, 
                              stagger_sec: int = 2, 
                              scope: str = "all"):
    
    # ⚡️ 在这里导入 TraderBot，因为它会引发巨型依赖链 (Strategies -> Numpy/OpenBB)
    from tradercat.bot import TraderBot

    start_time = datetime.now()
    bot = TraderBot(executor=executor)
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
            import traceback
            logger.error(traceback.format_exc())
    else:
        logger.info("Skipping Portfolio Strategies per scope.")

    # 2. Run Single-Asset Strategies
    if scope in ["all", "single"]:
        semaphore = asyncio.Semaphore(max_concurrency)

        async def worker(symbol):
            async with semaphore:
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
        save_signals_to_csv(all_results, drive_storage, scope)
        await send_discord_summary(discord_notifier, all_results)
    else:
        logger.info("No signals generated this session.")

    duration = datetime.now() - start_time
    logger.info(f"✅ Session finished in {duration.total_seconds():.2f}s")

# --- Entry Point ---

def main():
    parser = argparse.ArgumentParser(description="TraderCat Bot CLI")
    subparsers = parser.add_subparsers(dest="command", title="Available Commands")

    # --- Command: run ---
    run_parser = subparsers.add_parser("run", help="Start the trading session")
    run_parser.add_argument("-s", "--symbols", type=str, help="Comma separated symbols")
    run_parser.add_argument("-f", "--symbols-file", type=str, help="Path to symbols file")
    run_parser.add_argument("-c", "--concurrency", type=int, default=5, help="Max concurrent bots")
    run_parser.add_argument("-S", "--stagger", type=int, default=2, help="Stagger seconds")
    run_parser.add_argument("--scope", choices=["all", "single", "portfolio"], default="all", 
                        help="Execution scope: 'all' (default), 'single' (assets), or 'portfolio' strategies.")

    # --- Command: help ---
    subparsers.add_parser("help", help="Show this help message")

    args = parser.parse_args()
    
    if args.command == "run":
        # ⚡️ 只有在用户确定要 run 时，才导入这些重型模块
        logger.info("🚀 Initializing Trading Engine...")
        from tradercat.notification.discord import DiscordNotifier
        from tradercat.execution.trade_execution import TradeExecutor
        from tradercat.storage.google_drive import GoogleDriveStorage

        symbols = []
        if args.scope != "portfolio":
            symbols = load_symbols(args)
            logger.info(f"Loaded {len(symbols)} unique symbols from scope '{args.scope}'.")
            if not symbols:
                logger.error("No symbols found. Exiting.")
                return
        
        executor = TradeExecutor()
        notifier = DiscordNotifier()
        drive_storage = GoogleDriveStorage()

        try:
            asyncio.run(run_trading_session(symbols, executor, notifier, drive_storage, 
                                            args.concurrency, args.stagger, args.scope))
        except KeyboardInterrupt:
            logger.info("🛑 Bot stopped by user.")

    elif args.command == "help":
        parser.print_help()
        print("\n" + "-"*60)
        print("🚀 COMMAND: 'run' OPTIONS (Main Trading Engine)")
        print("-" * 60)
        run_parser.print_help()
    
    else:
        parser.print_help()
        print("\n💡 Tip: Type 'tradercat help' to see detailed options.")

if __name__ == "__main__":
    main()