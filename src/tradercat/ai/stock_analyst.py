import json
from typing import List, Any
from tradercat.ai.providers.llm_interface import LLMProvider
from tradercat.ai.prompt_manager import PromptManager
from tradercat.bot import TraderBot
from tradercat.utils.technical_indicators import TechUtils
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

class AIStockAnalyst:
    
    def __init__(self, llm: LLMProvider, bot: TraderBot, prompt_manager: PromptManager):
        self.llm = llm
        self.bot = bot
        self.prompt_manager = prompt_manager

    def _prepare_data_context(self, symbol: str, candles: List[Any]) -> str:
        """
        Constructs a Massive Quant Database for the LLM using extracted Utils.
        Includes comprehensive Trend, Momentum, Volatility, and Liquidity metrics.
        REFACTORED: To match updated TechUtils signatures (High/Low aware) & Volume Z-Score.
        """
        if not candles or len(candles) < 60:
            return json.dumps({"error": "Insufficient data (need 60+ candles)", "symbol": symbol})

        # 0. Data Prep (Safe attribute extraction)
        # Using list comprehensions for speed
        closes = [float(getattr(c, 'close', 0)) for c in candles]
        highs = [float(getattr(c, 'high', 0)) for c in candles]
        lows = [float(getattr(c, 'low', 0)) for c in candles]
        volumes = [float(getattr(c, 'volume', 0)) for c in candles]
        dates = [str(getattr(c, 'time', '')) for c in candles]
        
        curr = closes[-1]
        prev = closes[-2]
        
        # --- 1. HISTORICAL COMPUTATION (The "Tape") ---
        # "State" trajectory: We calc indicators for past 5 candles to show LLM the momentum slope.
        # Note: We pass sliced arrays to TechUtils to simulate 'past point in time'.
        
        tape_history = []
        for i in range(1, 6): # T-1 to T-5
            idx = -i
            # Slicing up to that point
            h_c = closes[:len(closes) - i + 1]
            h_h = highs[:len(highs) - i + 1]
            h_l = lows[:len(lows) - i + 1]
            h_v = volumes[:len(volumes) - i + 1]
            
            # Recalc dynamic indicators using correct OHLC signatures
            h_rsi = TechUtils.rsi(h_c, 14)
            h_macd = TechUtils.macd(h_c)
            h_bb = TechUtils.bollinger(h_c)
            h_adx = TechUtils.adx(h_h, h_l, h_c, 14) # Now uses highs/lows
            h_vol_z = TechUtils.volume_z_score(h_v, 30) # NEW: Historical Volume Z-Score
            
            tape_history.insert(0, {
                "date": dates[idx],
                "close": round(closes[idx], 2),
                "volume_hist": h_v[-1],
                "volume_z_5d": h_vol_z, # Capture history state of volume anomaly
                "rsi_14": h_rsi,
                "macd_hist": h_macd['hist'],
                "bb_width": h_bb.get('width_pct', 0),
                "adx": h_adx
            })

        # --- 2. RAW OHLCV HISTORY (Last 30 Days) ---
        # For Pattern Recognition (Head & Shoulders, Flags, etc.)
        ohlcv_30d = []
        start_idx = max(0, len(candles) - 30)
        for i in range(start_idx, len(candles)):
            c = candles[i]
            ohlcv_30d.append({
                "d": str(getattr(c, 'time', '')).split(' ')[0],
                "o": round(float(getattr(c, 'open', 0)), 2),
                "h": round(float(getattr(c, 'high', 0)), 2),
                "l": round(float(getattr(c, 'low', 0)), 2),
                "c": round(float(getattr(c, 'close', 0)), 2),
                "v": int(getattr(c, 'volume', 0))
            })

        # --- 3. TREND ANALYSIS (Current Snapshot) ---
        ema_12 = TechUtils.ema(closes, 12)[-1] if len(closes) > 12 else 0
        ema_26 = TechUtils.ema(closes, 26)[-1] if len(closes) > 26 else 0
        sma_50 = TechUtils.sma(closes, 50)
        sma_200 = TechUtils.sma(closes, 200)
        
        # New Signatures applied here:
        supertrend = TechUtils.supertrend(highs, lows, closes)
        ichimoku = TechUtils.ichimoku(highs, lows, closes)
        adx_val = TechUtils.adx(highs, lows, closes, 14)
        
        donchian = TechUtils.donchian(highs, lows, period=20)
        keltner = TechUtils.keltner(highs, lows, closes, period=20, atr_mult=2.0)

        # --- 4. MOMENTUM ANALYSIS (Current Snapshot) ---
        rsi = TechUtils.rsi(closes, 14)
        kdj = TechUtils.kdj(highs, lows, closes)
        cci = TechUtils.cci(highs, lows, closes, period=20)
        wr = TechUtils.williams_r(highs, lows, closes, period=14)
        mfi = TechUtils.mfi(highs, lows, closes, volumes, period=14)
        macd = TechUtils.macd(closes)

        # --- 5. VOLATILITY & LEVELS (Current Snapshot) ---
        atr = TechUtils.atr(highs, lows, closes, period=14)
        bb = TechUtils.bollinger(closes, period=20, std_dev=2)
        pivots = TechUtils.pivots(highs[-2], lows[-2], closes[-2]) # Yesterday's Pivots

        # --- 6. VOLUME & LIQUIDITY ---
        obv_state = TechUtils.obv_slope(closes, volumes)
        vwap = TechUtils.vwap_benchmark(closes, volumes, period=20)
        liq_ratio = TechUtils.liquidity_ratio(closes, volumes)
        
        # Calculate RVol Manually or use simple ratio
        vol_sma = TechUtils.sma(volumes, 20)
        rvol = (volumes[-1] / vol_sma) if vol_sma > 0 else 1.0

        # --- 7. LOGIC FIXES ---
        # MACD Logic: Compare Current Hist vs Previous (T-1 from tape_history)
        prev_macd_hist = tape_history[-1]['macd_hist'] if tape_history else 0
        macd_bullish = macd['hist'] > 0 and macd['hist'] > prev_macd_hist

        # Construct Final JSON structure
        context_data = {
            "meta": {
                "symbol": symbol,
                "price": round(curr, 2),
                "change_pct": round(((curr - prev) / prev) * 100, 2)
            },
            
            "raw_ohlcv_last_30": ohlcv_30d,

            "trend_matrix": {
                "ema_12": round(ema_12, 2),
                "ema_26": round(ema_26, 2),
                "supertrend_signal": supertrend.get("trend", "N/A"),
                "supertrend_level": supertrend.get("value", 0),
                "adx_strength": adx_val, 
                "adx_history_5d": [x['adx'] for x in tape_history], 
                "long_term_ma": "BULLISH" if (sma_200 > 0 and curr > sma_200) else "BEARISH",
                "golden_cross_potential": True if (sma_50 > sma_200 and sma_50 > 0) else False,
                
                "ichimoku_cloud": {
                    "signal": ichimoku.get("signal", "NEUTRAL"),
                    "position": "ABOVE_CLOUD" if curr > ichimoku.get("cloud_top", 999999) else "BELOW_OR_INSIDE"
                },
                "channel_boundaries": {
                    "donchian_upper": donchian.get("upper", 0),
                    "donchian_lower": donchian.get("lower", 0),
                    "keltner_upper": keltner.get("upper", 0)
                }
            },
            
            "momentum_oscillators": {
                "rsi_14": rsi, 
                "rsi_5d_history": [x['rsi_14'] for x in tape_history], 
                "macd": {
                    "histogram": macd['hist'], 
                    "history_5d": [x['macd_hist'] for x in tape_history], 
                    "crossover_signal": "BULLISH" if macd_bullish else "BEARISH"
                },
                "stochastics": {
                    "kdj": kdj, # Pass full dict {k, d, j}
                    "williams_r": wr 
                },
                "cci_20": cci,
                "mfi_money_flow": mfi,
                "volume_5d_history": [x['volume'] for x in tape_history],
            },

            "volatility_risk": {
                "atr_14": atr,
                "bollinger_bands": {
                    "width_pct": bb.get("width_pct", 0),
                    "width_history_5d": [x['bb_width'] for x in tape_history],
                    "squeeze_on": True if bb.get("width_pct", 1) < 0.10 else False, # < 10% width is a tight squeeze
                    "position_pct_b": round((curr - bb.get('lower',0)) / (bb.get('upper',1) - bb.get('lower',0)), 2) if bb.get('upper',1)!=bb.get('lower',0) else 0.5
                },
                "support_resistance_pivots": pivots
            },

            "liquidity_profile": {
                "smart_money_obv": obv_state,
                "vwap_benchmark": vwap,
                "relative_volume_rvol": round(rvol, 2),
                "volume_z_score": tape_history[-1]['volume_z_5d'] if tape_history else 0,
                "volume_z_score_5d_history": [x['volume_z_5d'] for x in tape_history], # Trajectory of anomalies
                "liquidity_impact_score": liq_ratio
            }
        }
        
        return json.dumps(context_data, indent=2)

    async def analyze_symbol(self, symbol: str, model_name: str, analyst_name: str = "wyckoff") -> str:
        
        request_id = f"{symbol}::{analyst_name}::{model_name}"
        logger.info(f"🧠 AI Analysis Request: {request_id}")

        candles = []
        try:
            # Lookback needs to be sufficient for 200 MA + Warmup for EMA/RMA
            candles = self.bot.data_provider.get_price_data(symbol, interval="1d", lookback=300)
            data_json_str = self._prepare_data_context(symbol, candles)
        except Exception as e:
            logger.warning(f"Data fetch warning for {symbol}: {e}")
            return f"⚠️ Data Error: {e}"
        
        try:
            lang_hint = analyst_name.lower().split("-")[1] if "-" in analyst_name else "en"
            # Get Prompt templates
            system_prompt = self.prompt_manager.get_system_prompt(analyst_name)
            # Make sure we pass the correct params to user_prompt
            user_prompt = self.prompt_manager.get_user_prompt(
                data_json=data_json_str, 
                lang_hint=lang_hint
            ) 
            
        except ValueError as e:
            logger.error(f"Template formatting failed: {e}")
            return f"❌ Prompt Error: {e}"

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