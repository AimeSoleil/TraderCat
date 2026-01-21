import asyncio
import traceback
from tradercat.logger.logger import get_logger
from tradercat.ai.llm_provider_factory_ import LLMFactory
from tradercat.ai.prompt_manager import PromptManager

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.table import Table
except ImportError:
    Console = None

logger = get_logger(__name__)

if Console is None:
    logger.warning("⚠️  'rich' library not found. Install it for a better UI: pip install rich")
# Initialize Console if available
console = Console() if Console else None

class AICommandHandler:
    """
    Controller class to handle all 'tradercat ai' CLI subcommands.
    Implements a View-Controller pattern where this class manages the UI/UX.
    """

    def list_models(self):
        """Displays supported AI models."""
        LLMFactory.list_all_supported_models()

    def list_personas(self):
        """Displays available analyst personas using Rich."""
        pm = PromptManager()
        personas = pm.list_analysts()
        
        if console:
            console.print("\n[bold cyan]🎭 Available Analyst Personas:[/bold cyan]")
            table = Table(show_header=False, box=None)
            for p in personas:
                table.add_row(f"[green]• {p}[/green]")
            console.print(table)
            console.print(f"\n[dim]💡 Usage: tradercat ai analyze TSLA --persona {personas[0] if personas else 'wyckoff'}[/dim]\n")
        else:
            print("\n🎭 Available Analyst Personas:")
            for p in personas:
                print(f"  • {p}")

    async def run_analysis(self, args):
        """
        Main execution flow with enhanced UI.
        Handles: Input Validation -> Provider Setup -> Bot Setup -> Report -> Chat Loop
        """
        # 1. Input Validation
        logger.info("Validating input symbol...")
        if not getattr(args, "symbol", None):
            self._print_error("Error: Symbol required. Usage: tradercat ai analyze TSLA")
            return
        
        # Taking only the first symbol for AI analysis as per design
        raw_symbols = [s.strip().upper() for s in args.symbol.split(",")]
        target_symbol = raw_symbols[0]
        if len(raw_symbols) > 1:
            logger.info(f"Multiple symbols provided in 'symbol' argument, using only {target_symbol} for analysis") 

        # 2. Setup LLM Provider
        logger.info("Setting up AI Provider...")
        try:
            llm_instance, model_name = LLMFactory.create_provider(args.model)
        except ValueError as e:
            self._print_error(f"Configuration Error: {e}")
            return

        # 3. Setup Components
        logger.info("Initializing Trading Bot and Analyst...")
        from tradercat.bot import TraderBot
        from tradercat.execution.trade_execution import TradeExecutor
        from tradercat.ai.stock_analyst import AIStockAnalyst
        
        executor = TradeExecutor() 
        bot = TraderBot(executor=executor) 
        prompt_manager = PromptManager()
        analyst = AIStockAnalyst(llm_instance, bot, prompt_manager)

        # 4. Header UI
        if console:
            grid_info = f"[bold cyan]Provider:[/bold cyan] {llm_instance.get_provider_name()} | [bold cyan]Model:[/bold cyan] {model_name} | [bold cyan]Persona:[/bold cyan] {args.persona}"
            console.print(Panel(grid_info, title=f"🧠 TraderCat Intelligence: {target_symbol}", border_style="blue"))
        else:
            print(f"🧠 Intelligence: {model_name} | Persona: {args.persona}")

        try:
            # A. Generate Initial Report with Spinner
            logger.info(f"Starting analysis for symbol: {target_symbol}")
            
            if console:
                with console.status(f"[bold green]🤖 {args.persona.capitalize()} is analyzing {target_symbol}...[/bold green]", spinner="dots"):
                    report = await analyst.analyze_symbol(
                        target_symbol, 
                        model_name=model_name, 
                        analyst_name=args.persona
                    )
                self._display_analysis(target_symbol, args.persona, report)
            else:
                print("Analyzing...")
                report = await analyst.analyze_symbol(target_symbol, model_name=model_name, analyst_name=args.persona)
                print(report)

            # B. Enter Chat Loop
            if not args.no_chat:
                await self._run_rich_chat_session(analyst, target_symbol, report, model_name, args.persona)

        except Exception as e:
            logger.error(f"Failed to analyze {target_symbol}: {e}")
            self._print_error(f"Error analyzing {target_symbol}: {e}")
            logger.debug(traceback.format_exc())

    def _display_analysis(self, symbol: str, persona: str, report_text: str):
        """Helper to print the main report as a Markdown Panel."""
        if console:
            md = Markdown(report_text)
            console.print(Panel(md, title=f"📊 Analysis Report: {symbol} ({persona})", border_style="green", expand=False))
            console.print()

    async def _run_rich_chat_session(self, analyst, symbol, initial_report, model_name, persona):
        """
        A visually improved chat loop using Rich.
        Orchestrates the UI here while using the analyst's purely functional LLM capability.
        """
        if console:
            console.print(Panel(f"[bold yellow]💬 Entering Live Chat with {persona.capitalize()}[/bold yellow]\n[dim]Ask follow-up questions about the chart or strategy. Type 'exit', 'quit', or 'q' to quit.[/dim]", border_style="yellow"))
        else:
            print(f"--- Chat with {persona} (type 'exit', 'quit', or 'q' to quit) ---")

        # Initialize History
        history = [
            {"role": "system", "content": f"You are a professional trader acting as {persona}. You have just analyzed {symbol}. Keep answers concise and strictly in character."},
            {"role": "assistant", "content": initial_report}
        ]

        while True:
            # 1. User Input
            try:
                if console:
                    user_text = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: Prompt.ask("\n[bold cyan]👤 You[/bold cyan]")
                    )
                else:
                    user_text = input("\nYou: ")
            except EOFError:
                if console:
                    console.print("[dim]👋 EOF received, ending session.[/dim]")
                else:
                    print("EOF received, ending session.")
                break
            if user_text.lower() in ["exit", "quit", "q"]:
                if console:
                    console.print("[dim]👋 Ending session.[/dim]")
                break
            
            if not user_text.strip():
                continue

            history.append({"role": "user", "content": user_text})

            # 2. AI Response
            try:
                if console:
                    with console.status(f"[bold magenta]🤖 {persona.capitalize()} is thinking...[/bold magenta]", spinner="earth"):
                        response_text = await analyst.llm.chat(history, model_id=model_name)
                    
                    # Markdown Rendering for Chat Bubbles
                    console.print(Panel(Markdown(response_text), title=f"🤖 {persona.capitalize()}", border_style="magenta", expand=False))
                else:
                    print("Thinking...")
                    response_text = await analyst.llm.chat(history, model_id=model_name)
                    print(f"\n{persona}: {response_text}")

            except Exception as e:
                self._print_error(f"AI Error: {e}")
                continue
            
            # 3. Update History
            history.append({"role": "assistant", "content": response_text})

    def _print_error(self, msg: str):
        if console:
            console.print(f"[bold red]❌ {msg}[/bold red]")
        else:
            print(f"❌ {msg}")