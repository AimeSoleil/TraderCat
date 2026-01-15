from tradercat.ai.llm_interface import LLMProvider
from tradercat.ai.prompt_manager import PromptManager
from tradercat.bot import TraderBot
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

class AIStockAnalyst:
    def __init__(self, llm: LLMProvider, bot: TraderBot, prompt_manager: PromptManager):
        self.llm = llm
        self.bot = bot
        self.prompt_manager = prompt_manager

    def _prepare_data_context(self, symbol: str, candles: list) -> dict:
        """
        Prepares a dictionary of data to be injected into the prompt template.
        """
        current_close = candles[-1].close
        prev_close = candles[-2].close
        
        # Simple calculations (expand this with real indicators later)
        daily_change_pct = ((current_close - prev_close) / prev_close) * 100
        
        # Calculate a basic 200 SMA manually for context
        closes = [c.close for c in candles]
        sma_200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else 0
        
        trend_status = "ABOVE 200 SMA (Bullish Bias)" if current_close > sma_200 else "BELOW 200 SMA (Bearish Bias)"
        
        # This string block corresponds to {market_data_block} in the prompt file
        data_block = f"""
        Symbol: {symbol}
        Latest Price: {current_close:.2f}
        Daily Change: {daily_change_pct:.2f}%
        Trend Context: {trend_status}
        Volume (Last): {candles[-1].volume}
        """
        
        return {
            "symbol": symbol,
            "curr_price": current_close,
            "market_data_block": data_block
        }

    async def analyze_symbol(self, symbol: str, analyst_name: str = "standard-en") -> str:
        """
        Pipe: Fetch Data -> Load Template -> Inject Data -> Call LLM
        """
        # 1. Fetch Data
        try:
            # Assuming bot has fetch_daily_candles implemented (from previous context)
            candles = self.bot.provider.fetch_daily_candles(symbol, limit=250)
            if not candles:
                return f"Error: No data found for {symbol}"
        except Exception as e:
            logger.error(f"Data fetch error: {e}")
            return f"Error fetching data for {symbol}"

        # 2. Load Prompt Template
        try:
            template = self.prompt_manager.get_prompt_template(analyst_name)
        except Exception as e:
            return f"Analyst Error: {str(e)}"

        # 3. Inject Data
        context_data = self._prepare_data_context(symbol, candles)
        
        # Safe format: only replaces keys that exist in the template
        # Using .format allows the text file to contain {curr_price}, {symbol}, etc.
        try:
            final_prompt = template.format(**context_data)
        except KeyError as e:
            # Fallback if the prompt file asks for data we didn't calculate
            logger.warning(f"Prompt template requested missing data: {e}")
            final_prompt = template # Send raw template or handle gracefully

        # 4. Call AI
        logger.info(f"🧠 {analyst_name} ({self.llm.get_model_name()}) is analyzing {symbol}...")
        analysis = await self.llm.generate_thought(final_prompt)
        
        return analysis