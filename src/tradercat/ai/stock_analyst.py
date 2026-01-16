import asyncio
from typing import List, Any
from tradercat.ai.llm_interface import LLMProvider
from tradercat.ai.prompt_manager import PromptManager
from tradercat.bot import TraderBot
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

class AIStockAnalyst:
    """
    Orchestrates the analysis process.
    Stateless regarding the Model ID (passed at runtime).
    """

    def __init__(self, llm: LLMProvider, bot: TraderBot, prompt_manager: PromptManager):
        self.llm = llm
        self.bot = bot
        self.prompt_manager = prompt_manager

    def _prepare_data_context(self, symbol: str, candles: List[Any]) -> dict:
        """
        Prepares a dictionary of data to be injected into the prompt template.
        Fixes: Uses the passed 'candles' argument, not self.candles.
        """
        # Safety Check
        if not candles or len(candles) < 2:
            return {
                "symbol": symbol,
                "curr_price": "N/A",
                "market_data_block": "Insufficient price data available."
            }
        
        # Access the last two candles
        current_candle = candles[-1]
        prev_candle = candles[-2]
        
        # Determine attribute names (pydantic object vs dict support)
        curr_close = getattr(current_candle, 'close', 0)
        prev_close = getattr(prev_candle, 'close', 0)
        volume = getattr(current_candle, 'volume', 0)
        
        # 1. Calculate Daily Change
        daily_change_pct = 0.0
        if prev_close > 0:
            daily_change_pct = ((curr_close - prev_close) / prev_close) * 100
        
        # 2. Basic Trend Context (Simple Moving Average approximation)
        closes = [getattr(c, 'close', 0) for c in candles]
        if len(closes) < 200:
            logger.warning(f"Not enough data to compute 200 SMA for {symbol}. Only {len(closes)} data points available.")
        recent_closes = closes[-200:]
        sma_200 = (sum(recent_closes) / len(recent_closes)) if recent_closes else 0
        
        trend_status = "Unknown"
        if sma_200 > 0:
            trend_status = "ABOVE 200 SMA (Bullish Bias)" if curr_close > sma_200 else "BELOW 200 SMA (Bearish Bias)"
        
        # 3. Construct Data Block
        data_block = f"""
        Symbol: {symbol}
        Latest Price: {curr_close:.2f}
        Daily Change: {daily_change_pct:.2f}%
        Trend Context: {trend_status}
        Volume (Last Session): {volume}
        """
        
        return {
            "symbol": symbol,
            "curr_price": f"{curr_close:.2f}",
            "market_data_block": data_block
        }

    async def analyze_symbol(self, symbol: str, model_name: str, analyst_name: str = "wyckoff") -> str:
        """
        Pipe: Load Template -> Fetch Data -> Call LLM (with specific model_name)
        """
        request_id = f"{symbol}::{analyst_name}::{model_name}"
        logger.info(f"🧠 AI Analysis Request: {request_id}")

        # 1. Fetch Data via Bot Executor or Data Provider
        candles = []
        try:
            candles = self.bot.data_provider.get_price_data(symbol, interval="1d", lookback=200)
        except Exception as e:
            logger.warning(f"Data fetch warning for {symbol}: {e}")
        
        if not candles:
            return f"⚠️ Data Error: Unable to retrieve price history for {symbol}."

        # 2. Load Prompt Template
        try:
            template = self.prompt_manager.get_prompt_template(analyst_name)
        except ValueError as e:
            return f"❌ Configuration Error: {str(e)}"

        # 3. Format Prompt
        try:
            data_context = self._prepare_data_context(symbol, candles)
            final_prompt = template.format(**data_context)
        except Exception as e:
            logger.error(f"Template formatting failed: {e}")
            return f"❌ Prompt Error: Failed to format analyst template."

        # 4. Call AI (Stateless Provider + Runtime Model ID)
        system_msg = f"You are a professional trader acting as {analyst_name}."
        
        try:
            analysis = await self.llm.generate_thought(
                prompt=final_prompt, 
                model_id=model_name,  # <--- [CRITICAL UPDATE] Passed at runtime
                system_prompt=system_msg
            )
            return analysis
        except Exception as e:
            logger.error(f"LLM Generation Failed ({model_name}): {e}")
            return f"❌ AI Generation Error: {str(e)}"

    async def start_chat_session(self, symbol: str, initial_report: str, model_name: str, analyst_name: str):
        """
        Starts an interactive session where context accumulates every round.
        """
        print(f"\n💬 Entering Live Chat with {analyst_name} (Symbol: {symbol})")
        print("   (Type 'exit', 'quit', or 'q' to stop)")
        print("-" * 60)

        # --- 1. BUILD INITIAL CONTEXT ---
        # The history list will grow with every turn.
        conversation_history = []

        # A. System Persona
        conversation_history.append({
            "role": "system",
            "content": f"You are a professional trader acting as {analyst_name}. You are discussing the stock {symbol}. Keep answers concise and strictly in character."
        })

        # B. The First Result (The Anchor)
        # We treat the initial report as an 'assistant' message that already happened.
        conversation_history.append({
            "role": "assistant",
            "content": initial_report
        })

        # --- 2. INTERACTIVE LOOP ---
        while True:
            # A. Get User Input
            try:
                # Use executor for input to avoid blocking the asyncio loop completely
                user_text = await asyncio.get_running_loop().run_in_executor(None, input, "\n👤 You: ")
            except EOFError:
                break
            
            user_text = user_text.strip()
            if user_text.lower() in ["exit", "q", "quit"]:
                print("👋 Session ended.")
                break
            
            if not user_text:
                continue

            # B. Append User Input to Context
            conversation_history.append({"role": "user", "content": user_text})
            
            print(f"🤖 {analyst_name} is thinking...")

            # C. Call AI with FULL Context
            response_text = await self.llm.chat(
                messages=conversation_history, 
                model_id=model_name
            )

            # D. Output & Append AI Response to Context
            print(f"\n🤖 {analyst_name}:\n{response_text}")
            
            # [CRITICAL] This ensures the *next* round knows what the AI just said
            conversation_history.append({"role": "assistant", "content": response_text})