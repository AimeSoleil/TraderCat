from typing import List, Optional, Dict, Any

from trade_bot.strategy.candle_pattern import CandlePatterns
from trade_bot.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from trade_bot.strategy.trading_strategy import ExitPlanner, TradingStrategy
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

class CandlestickReversalStrategy(TradingStrategy):
    """
    基于蜡烛图的反转策略（中文注释）
    要点：
        - 检测常见反转烛形：锤子/倒锤子、吞没、十字/十字星、刺透/乌云（此处实现为常见子集）
        - 使用 EMA 作为趋势过滤，ATR 作为止损尺度，RSI/MACD/成交量作为确认项
        - 返回 SignalModel，details 包含 entry/stop/target 与评分细节
    """
    def __init__(
        self,
        ema_fast: int = 13,
        ema_slow: int = 34,
        atr_period: int = 14,
        rsi_period: int = 14,
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        macd_params: Optional[Dict[str,int]] = None,
        min_atr_price_ratio: float = 0.02,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 1.0,
        score_threshold: float = 0.6,
        data_provider: Any = None
    ):
        self.ema_fast = int(ema_fast)
        self.ema_slow = int(ema_slow)
        self.atr_period = int(atr_period)
        self.rsi_period = int(rsi_period)
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.macd_params = macd_params or {"fast": 12, "slow": 26, "signal": 9}
        self.min_atr_price_ratio = min_atr_price_ratio
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

        # 指标字段名约定（provider 兼容）
        self.ema_fast_field = f"close_EMA_{self.ema_fast}"
        self.ema_slow_field = f"close_EMA_{self.ema_slow}"
        self.atr_field = f"ATRr_{self.atr_period}"
        self.rsi_field = f"close_RSI_{self.rsi_period}"
        self.adx_field = f"ADX_{self.adx_period}"
        self.macd_field = f"close_MACD_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_signal_field = f"close_MACDs_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_hist_field = f"close_MACDh_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"

    def get_name(self) -> str:
        return "CandlestickReversal"
    
    def get_lookback_window(self) -> int:
        """
        返回此策略需要的最小回溯 candle 数（用于判断是否有足够数据）。
        计算逻辑（经验规则）：
            - 至少包括慢速 EMA、ATR、RSI 与 MACD 的周期长度中的最大者
            - 再加少量安全边际
        这样在回测/实盘中能保证 provider 指标序列包含所需历史数据。
        """
        # 安全读取各指标周期（若未设置则使用合理默认）
        macd_max = max(int(self.macd_params.get("fast", 0) or 0),
                        int(self.macd_params.get("slow", 0) or 0),
                        int(self.macd_params.get("signal", 0) or 0))
        # 基础窗口取上述最大者
        base = max(self.ema_slow, self.atr_period, self.rsi_period, macd_max, 3)
        # 最后加上小的安全边际
        lookback = base + 3
        return int(lookback)

    # Supported scoring factors
    def support_scoring_factors(self) -> List[FactorName]:
        return  [
            FactorName.REVERSAL_CANDLE,
            FactorName.VOLUME_CONFIRM,
            FactorName.TREND_STRENGTH,
            FactorName.TREND_DIRECTION_CONFIRM,
            FactorName.MOMENTUM_CONFIRM,
            FactorName.CONFLUENCE_BONUS
        ]

    # ---------- 主决策逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        # ---------- 数据校验 ----------
        if not candles or len(candles) < max(self.ema_slow, self.atr_period, 3):
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold",
                                date=None, reason="insufficient data", confidence=0.0)

        # 提取 OHLCV 与日期
        opens = [float(getattr(c, "open")) for c in candles]
        highs = [float(getattr(c, "high")) for c in candles]
        lows = [float(getattr(c, "low")) for c in candles]
        closes = [float(getattr(c, "close")) for c in candles]
        vols = [getattr(c, "volume", None) for c in candles]
        dates = [getattr(c, "date", None) for c in candles]
        close = closes[-1]
        # ---------- 指标获取 ----------
        ema_fast_series = self.provider.get_indicator("ema", candles, {"length": self.ema_fast}) if self.provider else None
        ema_slow_series = self.provider.get_indicator("ema", candles, {"length": self.ema_slow}) if self.provider else None
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period}) if self.provider else None
        rsi_series = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period}) if self.provider else None
        macd_series = self.provider.get_indicator("macd", candles, self.macd_params) if (self.provider and self.macd_params) else None
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period}) if self.provider else None

        atr_val_history = [getattr(a, self.atr_field, None) for a in atr_series]
        adx_val_history = [getattr(a, self.adx_field, None) for a in adx_series]
        rsi_val_history = [getattr(r, self.rsi_field, None) for r in rsi_series]
        macd_hist_val_history = [getattr(m, self.macd_hist_field, None) for m in macd_series] if macd_series else []
        ema_fast_history = [getattr(m, self.ema_fast_field, None) for m in ema_fast_series]
        ema_slow_history = [getattr(m, self.ema_slow_field, None) for m in ema_slow_series]
        current_atr_val = atr_val_history[-1]
        current_adx_val = adx_val_history[-1]
        current_rsi_val = rsi_val_history[-1]
        current_ema_fast_val = ema_fast_history[-1]
        current_ema_slow_val = ema_slow_history[-1]

        # ---------- 烛形检测 (使用 CandlePatterns) ----------
        idx = len(candles) - 1
        found_bull, bull_pattern, bull_type = CandlePatterns.detect_bullish_pattern(opens, highs, lows, closes, idx)
        found_bear, bear_pattern, bear_type = CandlePatterns.detect_bearish_pattern(opens, highs, lows, closes, idx)
        pattern = bull_pattern if found_bull else (bear_pattern if found_bear else None)

        # ---------- 趋势判断 ----------
        trend_long = (current_ema_fast_val is not None and current_ema_slow_val is not None and current_ema_fast_val > current_ema_slow_val)
        trend_short = (current_ema_fast_val is not None and current_ema_slow_val is not None and current_ema_fast_val < current_ema_slow_val)

        # ---------- 趋势强度和波动率 -----------
        trend_strength = self._check_trend_and_volatility(
            atr_val_history=atr_val_history,
            adx_val_history=atr_val_history,
            close=close,
            window=100,
            atr_base_threshold=self.min_atr_price_ratio,
            atr_quantile=0.8,
            adx_quantile=0.8,
            mode='reversal'
        )

        # ---------- 成交量 z-score 确认 -----------
        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        vol_ok, volume_z = self._check_volume_zscore(vols, recent_window, self.vol_zscore_threshold)

        # ---------- 动量确认 ----------
        mom_ok = False
        if found_bull or found_bear:
            mom_ok = self._MOMENTUM_CONFIRM(rsi_val_history, macd_hist_val_history, prefer=bull_type if found_bull else bear_type)

        # ---------- 评分系统 ----------
        result: ScoringResult = None
        factors = [
            Factor(FactorName.REVERSAL_CANDLE, f"检测到拒绝蜡烛({pattern})", 0.35, found_bull or found_bear),
            Factor(FactorName.VOLUME_CONFIRM, "成交量放大确认", 0.2, vol_ok),
            Factor(FactorName.TREND_STRENGTH, "趋势强度和波动率确认", 0.15, trend_strength.signal),
            Factor(FactorName.TREND_DIRECTION_CONFIRM, "趋势方向一致", 0.15, (found_bull and trend_long) or (found_bear and trend_short)),
            Factor(FactorName.MOMENTUM_CONFIRM, "动量确认方向确认", 0.1, mom_ok),
            Factor(FactorName.CONFLUENCE_BONUS, "三重共振加分", 0.05, mom_ok and trend_strength.signal and ((found_bull and trend_long) or (found_bear and trend_short)))
        ]

        # Compute score using ScoringEngine
        engine = ScoringEngine(
            base_threshold=0.7, 
            required_factors=self.support_scoring_factors(),
            determined_factors=[
                FactorName.REVERSAL_CANDLE
            ]
        )
        side = "long" if found_bull else "short" if found_bear else "hold"
        result = engine.compute_score(factors, side=side)
        details = {
            "pattern": pattern,
            "ema_fast": current_ema_fast_val,
            "ema_slow": current_ema_slow_val,
            "atr": current_atr_val,
            "rsi": current_rsi_val,
            "adx": current_adx_val,
            "vol_zscore": round(volume_z, 3) if volume_z is not None else None,
            "score": round(result.score, 3),
        }
            
        # 计算入场止损与 trailing stop
        if result.signal != 'hold':
            planner = ExitPlanner(
                highs=highs,
                lows=lows,
                atr=current_atr_val,
                close_price=close
            )
            plan = planner.make_exit_plan('long' if result.signal == 'buy' else 'short')
            details.update({"plan": plan})

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=result.signal,
            date=dates[-1],
            confidence=round(result.score, 3),
            reason=" | ".join(result.reasons),
            details=details
        )

def make_candlestick_reversal_presets() -> Dict[str, Dict[str, Any]]:
    swing = {
        "ema_fast": 8,                     # Fast EMA for short-term trend
        "ema_slow": 21,                    # Slow EMA for trend confirmation
        "atr_period": 14,                  # ATR for volatility context
        "rsi_period": 14,                  # Standard RSI for reversal confirmation
        "adx_period": 14,                  # ADX standard period for trend strength
        "adx_threshold": 20.0,             # Lower threshold to allow reversals in weak trends
        "macd_params": {"fast": 12, "slow": 26, "signal": 9}, # Standard MACD settings
        "vol_zscore_window": 20,           # Match BB/EMA period for volume breakout detection
        "vol_zscore_threshold": 1.0,       # Stricter volume confirmation for reversal validity
        "score_threshold": 0.7,            # Slightly relaxed threshold for reversal signals
    }

    intermediate = {
        **swing,
    }

    position = {
        **swing,
    }

    return {"swing": swing, "intermediate": intermediate, "position": position}