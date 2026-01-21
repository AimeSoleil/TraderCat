import json
import statistics
from typing import List, Any
from tradercat.ai.providers.llm_interface import LLMProvider
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

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Helper: Calculate RSI using standard smoothing."""
        if len(prices) < period + 1:
            return 50.0 # Neural fallback
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gain = [x for x in deltas if x > 0]
        loss = [-x for x in deltas if x < 0]
        
        avg_gain = sum(gain) / period if gain else 0
        avg_loss = sum(loss) / period if loss else 0
        
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _prepare_data_context(self, symbol: str, candles: List[Any]) -> str:
        """
        Constructs a RICH DATA JSON string for the AI.
        Includes: Basic Snapshot, Technical Indicators, and Recent Tape (History).
        """
        # 1. Safety Checks
        if not candles or len(candles) < 20:
            return json.dumps({"error": "Insufficient data", "symbol": symbol})

        # Extract Lists for Math
        closes = [getattr(c, 'close', 0) for c in candles]
        volumes = [getattr(c, 'volume', 0) for c in candles]
        current = candles[-1]
        
        curr_price = closes[-1]
        prev_price = closes[-2]
        
        # 2. Compute Technical Indicators
        # -- Trend (SMA) --
        sma_20 = statistics.mean(closes[-20:])
        sma_50 = statistics.mean(closes[-50:]) if len(closes) >= 50 else 0
        sma_200 = statistics.mean(closes[-200:]) if len(closes) >= 200 else 0
        
        trend_state = "Neutral"
        if sma_50 > 0 and sma_200 > 0:
            if curr_price > sma_50 and sma_50 > sma_200: trend_state = "Strong Uptrend"
            elif curr_price < sma_50 and sma_50 < sma_200: trend_state = "Strong Downtrend"
        
        # -- Momentum (RSI) --
        rsi_14 = self._calculate_rsi(closes, 14)
        
        # -- Volatility / Change --
        daily_change_pct = ((curr_price - prev_price) / prev_price) * 100
        avg_vol = statistics.mean(volumes[-20:])
        rvol = (volumes[-1] / avg_vol) if avg_vol > 0 else 1.0
        
        # 3. Recent Price Action (The "Tape")
        # We give the LLM the last 7 days of raw data to find candlestick patterns
        recent_tape = []
        for c in candles[-7:]:
            date_str = getattr(c, 'time', 'N/A') # Adjust attribute based on your object
            recent_tape.append({
                "date": str(date_str),
                "open": round(getattr(c, 'open', 0), 2),
                "high": round(getattr(c, 'high', 0), 2),
                "low": round(getattr(c, 'low', 0), 2),
                "close": round(getattr(c, 'close', 0), 2),
                "volume": getattr(c, 'volume', 0)
            })

        # 4. Construct Final Structure
        context_data = {
            "meta": {
                "symbol": symbol,
                "interval": "1d",
                "observation_time": "Latest Close"
            },
            "snapshot": {
                "price": round(curr_price, 2),
                "change_percent": round(daily_change_pct, 2),
                "volume": volumes[-1],
                "relative_volume_rvol": round(rvol, 2)
            },
            "technicals": {
                "rsi_14": round(rsi_14, 2),
                "sma_20": round(sma_20, 2),
                "sma_50": round(sma_50, 2),
                "sma_200": round(sma_200, 2),
                "trend_assessment": trend_state,
                "price_vs_sma200": "ABOVE" if curr_price > sma_200 else "BELOW"
            },
            "recent_candle_tape": recent_tape
        }
        
        # Return as JSON string directly to be injected into prompt
        return json.dumps(context_data, indent=2)

    async def analyze_symbol(self, symbol: str, model_name: str, analyst_name: str = "wyckoff") -> str:
        
        request_id = f"{symbol}::{analyst_name}::{model_name}"
        logger.info(f"🧠 AI Analysis Request: {request_id}")

        # 1. Fetch Data
        candles = []
        try:
            candles = self.bot.data_provider.get_price_data(symbol, interval="1d", lookback=250)
            # data_json_str IS NOW A JSON STRING
            data_json_str = self._prepare_data_context(symbol, candles)
        except Exception as e:
            logger.warning(f"Data fetch warning for {symbol}: {e}")
            return f"⚠️ Data Error: {e}"
        
        # 2. Load Prompts
        try:
            lang_hint = analyst_name.lower().split("-")[1] if "-" in analyst_name else "en"
            system_prompt = self.prompt_manager.get_system_prompt(analyst_name)
            
            # 3. Inject JSON into User Prompt Template
            # ensure get_user_prompt accepts the string directly
            user_prompt = self.prompt_manager.get_user_prompt(data_json=data_json_str, lang_hint=lang_hint) 
            
        except ValueError as e:
            logger.error(f"Template formatting failed: {e}")
            return f"❌ Prompt Error: {e}"

        # 4. Call AI
        try:
            analysis = await self.llm.generate_thought(
                prompt=user_prompt, 
                model_id=model_name,
                system_prompt=system_prompt
            )
            return analysis
        except Exception as e:
            logger.error(f"LLM Error: {e}")
            return f"❌ AI Generation Error: {str(e)}"