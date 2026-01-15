import os
import yaml
from typing import List
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

class SymbolLoader:
    """
    Handles the logic for retrieving target symbols from various sources:
    1. CLI arguments (-s AAPL,TSLA)
    2. File input (-f symbols.yaml)
    3. Environment variables (ENV_SYMBOLS)
    """

    @staticmethod
    def load_symbols(args) -> List[str]:
        """
        Determines the source of symbols and loads them into a unique list.
        """
        symbols = []
        
        # 1. Check CLI Argument
        if args.symbols:
            logger.info(f"Symbols source: CLI Args ({args.symbols})")
            symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        
        # 2. Check File Argument
        elif args.symbols_file:
            logger.info(f"Symbols source: File ({args.symbols_file})")
            if not os.path.exists(args.symbols_file):
                logger.error(f"File not found: {args.symbols_file}")
                return []

            ext = os.path.splitext(args.symbols_file)[1].lower()
            try:
                with open(args.symbols_file, "r") as f:
                    if ext in [".yaml", ".yml"]:
                        data = yaml.safe_load(f)
                        symbols = [s.strip().upper() for s in data.get("symbols", [])]
                    else:
                        # Assume text file (one symbol per line)
                        symbols = [line.strip().upper() for line in f if line.strip()]
            except Exception as e:
                logger.error(f"Failed to read symbols file: {e}")
                return []
        
        # 3. Check Environment Variable
        else:
            env_symbols = os.environ.get("ENV_SYMBOLS")
            if env_symbols:
                logger.info("Symbols source: ENV_SYMBOLS")
                symbols = [s.strip().upper() for s in env_symbols.split(",") if s.strip()]
            else:
                logger.warning("No symbols provided via CLI, File, or ENV.")

        # Remove duplicates while preserving order
        unique_symbols = list(dict.fromkeys(symbols))
        
        if unique_symbols:
            logger.info(f"✅ Loaded {len(unique_symbols)} unique symbols.")
        
        return unique_symbols