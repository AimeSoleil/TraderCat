import traceback
from tradercat.logger.logger import get_logger
from tradercat.ai.llm_provider import LLMFactory
from tradercat.ai.prompt_manager import PromptManager

logger = get_logger(__name__)

class AICommandHandler:
    """
    Controller class to handle all 'tradercat ai' CLI subcommands.
    Encapsulates logic for model selection, symbol validation, and interaction loops.
    """

    def list_models(self):
        """Displays supported AI models."""
        LLMFactory.list_all_supported_models()

    def list_personas(self):
        """Displays available analyst personas."""
        pm = PromptManager()
        personas = pm.list_analysts()
        
        print("\n🎭 Available Analyst Personas:")
        print("=" * 40)
        for p in personas:
            print(f"  • {p}")
        print("=" * 40)
        print(f"💡 Usage Example: tradercat ai analyze TSLA --persona {personas[0] if personas else 'wyckoff'}")

    async def run_analysis(self, args):
        """
        Main execution flow for 'ai analyze'.
        Handles: Input Validation -> Provider Setup -> Bot Setup -> Report -> Chat Loop
        """
        # 1. Input Validation & Single Symbol Enforcement
        if not getattr(args, "symbol", None):
            print("❌ Error: You must specify a symbol. Usage: tradercat ai analyze TSLA")
            return
        target_symbol = args.symbol.strip().upper()
        if not target_symbol:
            print("❌ Error: You must specify a symbol. Usage: tradercat ai analyze TSLA")
            return

        # 2. Setup LLM Provider
        try:
            llm_instance, model_name = LLMFactory.create_provider(args.model)
        except ValueError as e:
            print(f"❌ Configuration Error: {e}")
            return

        # 3. Setup Trading Components (Lazy imports to keep CLI fast)
        from tradercat.bot import TraderBot
        from tradercat.execution.trade_execution import TradeExecutor
        from tradercat.ai.stock_analyst import AIStockAnalyst
        
        # Mock executor because AI analysis is read-only regarding trades
        executor = TradeExecutor() 
        bot = TraderBot(executor=executor) 
        prompt_manager = PromptManager()
        
        # Initialize Analyst (Stateless regarding model)
        analyst = AIStockAnalyst(llm_instance, bot, prompt_manager)

        # 4. Execution UI
        print(f"\n🧠 Intelligence Provider: {llm_instance.get_provider_name()} (Model: {model_name})")
        print(f"🎭 Analyst Persona:     {args.persona}")
        print("=" * 60)

        try:
            # A. Provide Initial Analysis
            report = await analyst.analyze_symbol(
                target_symbol, 
                model_name=model_name, 
                analyst_name=args.persona
            )
            
            print(f"\n📊 ANALYSIS REPORT: [{target_symbol}]")
            print("-" * 60)
            print(report)
            print("-" * 60)

            # B. Enter Chat Loop (Conversational Mode)
            if not args.no_chat:
                await analyst.start_chat_session(
                    symbol=target_symbol,
                    initial_report=report,
                    model_name=model_name,
                    analyst_name=args.persona
                )

        except Exception as e:
            logger.error(f"Failed to analyze {target_symbol}: {e}")
            print(f"❌ Error analyzing {target_symbol}: {e}")
            logger.debug(traceback.format_exc())