import asyncio
import argparse
import traceback

# Component Imports
from tradercat.logger.logger import get_logger
from tradercat.ai.ai_commands import AICommandHandler
from tradercat.utils.symbol_loader import SymbolLoader
from tradercat.core.session_runner import SessionRunner

logger = get_logger(__name__)

def main():
    parser = argparse.ArgumentParser(description="TraderCat: AI-Powered Trading Terminal")
    subparsers = parser.add_subparsers(dest="command", title="Root Commands")

    # ==========================
    # 1. RUN (Trading Engine)
    # ==========================
    run_parser = subparsers.add_parser("run", help="Start the automated trading engine")
    run_parser.add_argument("-s", "--symbols", type=str, help="Comma separated symbols (e.g. AAPL,TSLA)")
    run_parser.add_argument("-f", "--symbols-file", type=str, help="Path to symbols file (YAML/TXT)")
    run_parser.add_argument("-c", "--concurrency", type=int, default=5, help="Max concurrent bots")
    run_parser.add_argument("-S", "--stagger", type=int, default=2, help="Stagger seconds")
    run_parser.add_argument("--scope", choices=["all", "single", "portfolio"], default="single", 
                        help="Execution scope: 'single' (assets), 'all' (single + portfolio), or 'portfolio'")

    # ==========================
    # 2. AI (Intelligence Hub)
    # ==========================
    ai_parser = subparsers.add_parser("ai", help="Global Market Intelligence Tools")
    ai_subparsers = ai_parser.add_subparsers(dest="ai_command", title="AI Actions")

    # [Action] analyze
    analyze_parser = ai_subparsers.add_parser("analyze", help="Generate technical deep-dive reports")
    analyze_parser.add_argument("symbols", type=str, help="Target Symbol (Single ticker only, e.g. TSLA)")
    analyze_parser.add_argument("-m", "--model", type=str, default="copilot_gpt-4o", 
                            help="AI Provider string (e.g. copilot_gpt-4o, mock)")
    analyze_parser.add_argument("-p", "--persona", type=str, default="wyckoff", 
                            help="Analyst Personality (e.g. buffett, livermore)")
    analyze_parser.add_argument("--no-chat", action="store_true", help="Disable follow-up chat session")
    
    # [Action] list-models
    ai_subparsers.add_parser("list-models", help="Combined view of AI providers and models")
    
    # [Action] list-personas
    ai_subparsers.add_parser("list-personas", help="Show available analyst personalities")

    # ==========================
    # 3. HELP
    # ==========================
    subparsers.add_parser("help", help="Show full help message")

    # --- EXECUTION ROUTING ---
    args = parser.parse_args()
    
    try:
        # --- ROUTE: TRADING ENGINE ---
        if args.command == "run":
            logger.info("🚀 Initializing Trading Engine...")
            
            # Sub-component imports (Lazy loading for speed)
            from tradercat.notification.discord import DiscordNotifier
            from tradercat.execution.trade_execution import TradeExecutor
            from tradercat.storage.google_drive import GoogleDriveStorage

            # 1. Load Symbols
            symbols = []
            if args.scope != "portfolio":
                symbols = SymbolLoader.load_symbols(args)
                if not symbols:
                    logger.error("No valid symbols found. Exiting.")
                    return
            
            # 2. Init Dependencies
            executor = TradeExecutor()
            notifier = DiscordNotifier()
            drive_storage = GoogleDriveStorage()

            # 3. Delegate to Runner
            runner = SessionRunner(executor, notifier, drive_storage)
            asyncio.run(runner.run_session(
                symbols, 
                args.concurrency, 
                args.stagger, 
                args.scope
            ))

        # --- ROUTE: AI COMMANDS ---
        elif args.command == "ai":
            # Delegate all AI logic to the Controller
            ai_handler = AICommandHandler()

            if args.ai_command == "analyze":
                asyncio.run(ai_handler.run_analysis(args))
            elif args.ai_command == "list-models":
                ai_handler.list_models()
            elif args.ai_command == "list-personas":
                ai_handler.list_personas()
            else:
                ai_parser.print_help()

        # --- ROUTE: HELP / DEFAULT ---
        elif args.command == "help":
            parser.print_help()
        else:
            parser.print_help()

    except KeyboardInterrupt:
        logger.info("🛑 Operation cancelled by user.")
    except Exception as e:
        logger.error(f"Fatal Global Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()