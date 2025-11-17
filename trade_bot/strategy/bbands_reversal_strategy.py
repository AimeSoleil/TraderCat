import logging
from typing import List, Optional, Dict, Any, Tuple
import statistics

from trade_bot.strategy.candle_pattern import CandlePatterns
from trade_bot.strategy.trading_strategy import TradingStrategy, EPS
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

class BBandsReversalStrategy(TradingStrategy):
    """
    基于布林带的反转策略
    核心思想：
        - 当价格接近上/下轨并出现拒绝性蜡烛（长影线、吞没、反转实体）时，作为反转候选
        - 用 ATR 过滤低波动、用 ADX 避免强趋势中做逆向交易，用成交量 z-score 与动量作为确认
        - 可配置的确认窗口（max_time_bars），以及 presets（swing/intermediate/position）
    输出：
        SignalModel(signal in {'buy','sell','hold'}, confidence, reason(中文), details)
    """

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        touch_pct: float = 0.03,  # 价格与带位的相对容差（3%以内视为“接触”）
        rsi_period: int = 14,
        atr_period: int = 14,
        adx_period: int = 14,
        adx_threshold: float = 30.0,  # ADX 超过视为强趋势，避免逆势反转
        max_time_bars: int = 3,  # 延续/确认窗口
        min_atr_price_ratio: float = 0.001,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 1.0,
        macd_params: Optional[Dict[str, int]] = {"fast": 12, "slow": 26, "signal": 9},
        score_threshold: float = 0.6,
        data_provider=None,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.touch_pct = float(touch_pct)
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.adx_period = adx_period
        self.adx_threshold = float(adx_threshold)
        self.max_time_bars = int(max_time_bars)
        self.min_atr_price_ratio = float(min_atr_price_ratio)
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.macd_params = macd_params or {"fast": 12, "slow": 26, "signal": 9}
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

        # 字段名（兼容 provider 产出）
        self.bb_bw_field = f"close_BBB_{self.bb_period}_{self.bb_std}"
        self.bb_up_field = f"close_BBU_{self.bb_period}_{self.bb_std}"
        self.bb_low_field = f"close_BBL_{self.bb_period}_{self.bb_std}"
        self.bb_mid_field = f"close_BBM_{self.bb_period}_{self.bb_std}"
        self.atr_field = f"ATRr_{self.atr_period}"
        self.rsi_field = f"close_RSI_{self.rsi_period}"
        self.macd_field = f"close_MACD_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_signal_field = f"close_MACDs_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_hist_field = f"close_MACDh_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.adx_field = f"ADX_{self.adx_period}"

    def get_name(self) -> str:
        return "BBandsReversal"

    def get_lookback_window(self) -> int:
        return (
            max(
                self.bb_period,
                self.rsi_period,
                self.atr_period,
                self.max_time_bars,
                (self.macd_params["slow"] or 0),
            )
            + 5
        )

    # ---------- 工具 ----------
    def _extract_latest_indicator_value(
        self, series: Optional[List[Any]], keys: List[str]
    ) -> Optional[float]:
        if not series:
            return None
        last = series[-1]
        if last is None:
            return None
        for k in keys:
            try:
                v = getattr(last, k)
            except Exception:
                v = None
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    continue
        return None

    def _momentum_confirmation(
        self,
        rsi_series: Optional[List[Any]],
        macd_series: Optional[List[Any]],
        prefer: str = "bull",
    ) -> bool:
        # 简单动量确认：RSI or MACD hist 指向反转方向
        r_latest = self._extract_latest_indicator_value(rsi_series, [self.rsi_field])
        macd_hist_latest = None
        if macd_series:
            macd_hist_latest = getattr(macd_series[-1], self.macd_hist_field, None)

        if prefer == "bull":
            if r_latest is not None and r_latest > 30:
                return True
            if macd_hist_latest is not None and macd_hist_latest > 0:
                return True
            return False
        else:
            if r_latest is not None and r_latest < 70:
                return True
            if macd_hist_latest is not None and macd_hist_latest < 0:
                return True
            return False

    # ---------- 主逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        if not candles or len(candles) < self.get_lookback_window():
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=candles[-1].date if candles else None,
                reason="数据不足",
                confidence=0.0,
            )

        # 获取指标
        bb = self.provider.get_indicator("bbands", candles, {"length": self.bb_period, "std": self.bb_std})
        atr = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        macd = self.provider.get_indicator("macd", candles, self.macd_params)
        adx = self.provider.get_indicator("adx", candles, {"length": self.adx_period})

        closes = [float(c.close) for c in candles]
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        opens = [float(c.open) for c in candles]
        vols = [float(c.volume) for c in candles]
        dates = [c.date for c in candles]
        idx = len(candles) - 1
        close = closes[-1]
        prev_close = closes[-2] if len(closes) >= 2 else close

        # 读取当前带位
        try:
            bb_last = bb[-1]
            u_curr = getattr(bb_last, self.bb_up_field, None)
            l_curr = getattr(bb_last, self.bb_low_field, None)
            m_curr = getattr(bb_last, self.bb_mid_field, None)
        except Exception:
            u_curr = l_curr = m_curr = None

        # ATR 与波动性 guard
        atr_val = self._extract_latest_indicator_value(atr, [self.atr_field])
        vol_guard_ok = (
            atr_val / (close if abs(close) > EPS else 1.0)
        ) >= self.min_atr_price_ratio

        # ADX（避免在强趋势中做逆势）
        adx_val = self._extract_latest_indicator_value(adx, [self.adx_field]) if adx else None
        adx_ok = True if (adx_val is None or adx_val <= self.adx_threshold) else False

        # 成交量 z-score
        vol_ok = False
        volume_z = None
        recent_window = max(
            2, min(self.vol_zscore_window, len([v for v in vols if v is not None]))
        )
        recent_vols = [v for v in vols[-recent_window:] if v is not None]
        try:
            if recent_vols and len(recent_vols) >= 2 and vols[-1] is not None:
                mean_v = sum(recent_vols) / len(recent_vols)
                std_v = statistics.pstdev(recent_vols) if len(recent_vols) > 1 else 0.0
                if std_v > 0:
                    volume_z = (vols[-1] - mean_v) / std_v
                    vol_ok = volume_z >= self.vol_zscore_threshold
        except Exception:
            vol_ok = False

        # 检查是否接近上轨/下轨（相对容差
        near_upper = (u_curr is not None) and (
            abs(close - u_curr) / (u_curr if abs(u_curr) > EPS else 1.0)
            <= self.touch_pct
            or close > u_curr
        )
        near_lower = (l_curr is not None) and (
            abs(close - l_curr) / (l_curr if abs(l_curr) > EPS else 1.0)
            <= self.touch_pct
            or close < l_curr
        )

        # 检测拒绝蜡烛（以最近 self.max_time_bars 根内的任意一根作为确认）
        rejection_found = False
        rejection_type = None
        pattern_type = None
        reject_idx = None
        start = max(0, idx - self.max_time_bars + 1)
        for i in range(start, idx + 1):
            if near_lower:
                rejection_found, rejection_type, pattern_type = CandlePatterns.detect_bullish_pattern(opens, highs, lows, closes, i)
                reject_idx = i
                break
            # 看空候选（接近上轨）
            if near_upper:
                rejection_found, rejection_type, pattern_type = CandlePatterns.detect_bearish_pattern(opens, highs, lows, closes, i)
                reject_idx = i
                break

        # 动量确认（若启用）
        momentum_ok = False
        if near_upper or pattern_type == "bearish":
            self._momentum_confirmation(rsi, macd, prefer="bear")
        elif near_lower or pattern_type == "bullish":
            self._momentum_confirmation(rsi, macd, prefer="bull")
        else:
            momentum_ok = False

        # 评分构成（中文 reason）
        score = 0.0
        reasons: List[str] = []
        details: Dict[str, Any] = {
            "close": close,
            "upper": u_curr,
            "lower": l_curr,
            "mid": m_curr,
            "atr": round(atr_val, 6),
            "adx": round(adx_val, 3) if adx_val is not None else None,
            "vol_zscore": round(volume_z, 3) if volume_z is not None else None,
            "vol_guard_ok": vol_guard_ok,
            "near_upper": near_upper,
            "near_lower": near_lower,
            "rejection_found": rejection_found,
            "rejection_type": rejection_type,
            "reject_idx": reject_idx,
        }

        # 基本条件判断
        if not vol_guard_ok:
            reasons.append("波动性过低（ATR/价格 未达到阈值）")
        if not adx_ok:
            reasons.append("ADX 显示强趋势，不建议逆势开仓")
        # 只有在带位接近并出现拒绝蜡烛的情况下考虑反转
        candidate_buy = near_lower and rejection_found
        candidate_sell = near_upper and rejection_found

        if candidate_buy or candidate_sell:
            reasons.append(f"检测到带位拒绝蜡烛（{rejection_type}）")
            score += 0.35
            # 波动性与adx必须基本通过
            if vol_guard_ok:
                score += 0.2
                reasons.append("波动性通过")
            if adx_ok:
                score += 0.2
                reasons.append("ADX 允许逆势")
            # 成交量确认
            if vol_ok:
                score += 0.15
                reasons.append("成交量放大确认")
            else:
                # 若无明显量能，给予部分权重但降低信心
                score += 0.05
                reasons.append("无明显放量（降权）")
            # 动量确认
            if momentum_ok:
                score += 0.10
                reasons.append("动量方向确认")
            # 附加：若拒绝蜡烛出现在极端 shadow 并且接近 mid 线穿越，额外加分
            if candidate_buy and prev_close > m_curr and close < m_curr:
                score += 0.05
                reasons.append("下穿中轨后反转（加分）")
            if candidate_sell and prev_close < m_curr and close > m_curr:
                score += 0.05
                reasons.append("上穿中轨后反转（加分）")
        else:
            reasons.append("未满足带位拒绝 + 确认条件")
            score += 0.0

        confidence = min(1.0, score)
        details["score"] = round(score, 3)

        # 计算止损/目标（以 ATR 为单位）
        entry_price = close
        stop_loss = None
        target = None
        signal = "hold"
        if candidate_buy and confidence >= self.score_threshold:
            signal = "buy"
            stop_loss = (
                min(lows[max(0, idx - 3) : idx + 1]) - self.atr_period * 0
            )
            target = round(
                entry_price
                + max(
                    self.atr_period * 0 + atr_val * 2.0, (entry_price - stop_loss) * 1.8
                ),
                6,
            )
            reasons.append("生成买入信号")
        elif candidate_sell and confidence >= self.score_threshold:
            signal = "sell"
            stop_loss = round(entry_price + (self.atr_period * 0 + atr_val * 1.5), 6)
            target = round(
                entry_price
                - max(
                    self.atr_period * 0 + atr_val * 2.0, (stop_loss - entry_price) * 1.8
                ),
                6,
            )
            reasons.append("生成卖出信号")
        else:
            reasons.append("未达到置信度或条件，保持观望")

        details.update(
            {
                "entry": entry_price,
                "stop_loss": stop_loss,
                "target": target,
                "reasons": reasons,
            }
        )

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            date=dates[-1],
            confidence=round(confidence, 3),
            reason=" | ".join(reasons),
            details=details,
        )

def make_bbands_reversal_presets() -> Dict[str, Dict[str, Any]]:
    """
    依据实战与最佳实践的预设（swing/intermediate/position）
    """
    swing = {
        "bb_period": 20,
        "bb_std": 2.0,
        "touch_pct": 0.05,
        "rsi_period": 9,
        "atr_period": 14,
        "adx_period": 10,
        "adx_threshold": 25.0,
        "max_time_bars": 3,
        "min_atr_price_ratio": 0.001,
        "vol_zscore_window": 10,
        "vol_zscore_threshold": 0.8,
        # "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "score_threshold": 0.55,
    }
    intermediate = {
        "bb_period": 20,
        "bb_std": 2.0,
        "touch_pct": 0.03,
        "rsi_period": 14,
        "atr_period": 14,
        "adx_period": 14,
        "adx_threshold": 25.0,
        "max_time_bars": 5,
        "min_atr_price_ratio": 0.0015,
        "vol_zscore_window": 20,
        "vol_zscore_threshold": 1.0,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "score_threshold": 0.75,
    }
    position = {
        "bb_period": 20,
        "bb_std": 2.0,
        "touch_pct": 0.04,
        "rsi_period": 21,
        "atr_period": 21,
        "adx_period": 28,
        "adx_threshold": 30.0,
        "max_time_bars": 8,
        "min_atr_price_ratio": 0.002,
        "vol_zscore_window": 40,
        "vol_zscore_threshold": 1.2,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "score_threshold": 0.8,
    }
    return {"swing": swing, "intermediate": intermediate, "position": position}
