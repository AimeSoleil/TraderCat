from typing import List, Optional, Dict, Any, Union, Literal
from pydantic import BaseModel
from scipy.stats import zscore
import numpy as np
import pandas as pd

from tradercat.data.market_data_provider import MarketDataProvider
from tradercat.strategy.trading_strategy import TradingStrategy
from tradercat.strategy.signal_model import SignalModel
from tradercat.logger.logger import get_logger
from tradercat.strategy.strategy_presets import SectorRotationPreset

logger = get_logger(__name__)

# 1. Broad GICS Sectors (Good for "Position" / Long-term)
# 宽基板块：适合长期配置和捕捉宏观经济周期
# 这些是美股市场的 11 根支柱，涵盖了经济的方方面面。
GICS_SECTOR_LIST = {
    # --- 进攻型 (Cyclical / Growth) ---
    "Technology": "XLK",       # 科技 (Technology): 包含微软、英伟达。牛市的核心驱动力，对利率敏感，高成长。
    "Discretionary": "XLY",    # 可选消费 (Consumer Discretionary): 包含亚马逊、特斯拉。反映消费者信心和经济繁荣度。
    "Comms": "XLC",            # 通讯服务 (Communication Services): 包含谷歌、Meta、奈飞。广告收入和数字媒体驱动。
    
    # --- 周期型 (Cyclical / Value) ---
    "Financials": "XLF",       # 金融 (Financials): 包含摩根大通、伯克希尔。受益于经济复苏和适度的高利率。
    "Industrials": "XLI",      # 工业 (Industrials): 包含通用电气、卡特彼勒。制造业回流和基础设施建设受益者。
    "Materials": "XLB",        # 原材料 (Materials): 包含林德气体。通胀初期表现好，与大宗商品价格挂钩。
    "Energy": "XLE",           # 能源 (Energy): 包含埃克森美孚。地缘政治风险和通胀的对冲工具。
    
    # --- 防御型 (Defensive / Yield) ---
    "Health Care": "XLV",      # 医疗 (Health Care): 包含联合健康、强生。抗跌属性强，老龄化长期受益，不受经济周期影响。
    "Staples": "XLP",          # 必选消费 (Consumer Staples): 包含宝洁、可口可乐。熊市避风港，抗通胀，现金流稳定。
    "Utilities": "XLU",        # 公用事业 (Utilities): 包含电力公司。类债券资产，高股息。在降息周期表现优异。
    "Real Estate": "XLRE",     # 房地产 (Real Estate): 包含REITs。高股息，抗通胀，但对高利率极其敏感。
}

# 2. [NEW] Heated Sub-Sectors (Best for "Swing" / Momentum)
# 热门细分赛道：适合波段交易，高Beta，捕捉热钱流向
# Updated based on 2024-2025 Market Themes
SUB_SECTOR_LIST = {
    # --- 核心科技 (Core Tech) ---
    "Semiconductors": "SMH",   # 半导体: AI 算力核心 (Nvidia, TSMC)。绝对的市场总龙头。
    "Software": "IGV",         # 软件/SaaS: 高估值科技 (Salesforce, Oracle)。牛市弹性大。
    "Cybersecurity": "CIBR",   # 网络安全: 刚需科技 (Palo Alto, CrowdStrike)。地缘政治受益。
    
    # --- 激进成长 (Aggressive Growth) ---
    "Biotech": "XBI",          # 生物科技: 极高波动。中小药企，受利率和并购消息驱动。
    "Blockchain": "BLOK",      # 区块链: 加密资产代理。波动率之王，比特币行情的影子股。
    "China Tech": "KWEB",      # 中国互联网: 离岸资产。腾讯、阿里。用于捕捉非美市场的剧烈波动。

    # --- 能源与大宗 (Energy & Commodities) ---
    "Oil & Gas E&P": "XOP",    # 油气开采: 激进能源。纯上游，油价杠杆。
    "Uranium": "URA",          # 铀/核能: AI电力需求/能源转型。新的结构性牛市赛道。
    "Copper": "COPX",          # 铜矿: 电气化/经济复苏。比黄金更具工业属性的金属。
    "Gold Miners": "GDX",      # 金矿: 避险/通胀。黄金价格的放大器。

    # --- 周期与宏观 (Cyclical & Macro) ---
    "Homebuilders": "XHB",     # 房屋建筑: 利率敏感。美国实体经济晴雨表。
    "Defense": "ITA",          # 国防军工: 地缘对冲。战争风险时的避风港。
}

class Indicators(BaseModel):
    rsi: Optional[float]
    volatility: Optional[float]
    momentum: Optional[float]
    avg_volume: Optional[float]
    volume_trend: Optional[float]
    composite_score: Optional[float] = 0.0

class SectorRotationStrategy(TradingStrategy):
    """
    Sector Rotation Strategy (Refactored)
    - Supports both Broad GICS sectors and Granular Sub-sectors.
    - Uses Z-Score for robust ranking.
    - Configurable Market Regime.
    """

    def __init__(
        self,
        look_back_days: int = 20,
        num_sectors_to_select: int = 3,
        rsi_period: int = 14,
        atr_period: int = 14,
        regime_sma_period: int = 200,
        max_entry_rsi: float = 85.0,
        weights: Optional[Dict[str, float]] = None,
        # [New] Allow choosing the universe
        universe: Union[str, Dict[str, str]] = "sub_sector", 
        data_provider: MarketDataProvider = None,
        safe_haven_symbol: str = "SHY",  # [New] Configurable Safe Haven
        benchmark_symbol: str = "SPY",   # [New] Configurable Benchmark
    ):
        self.look_back_days = look_back_days
        self.num_sectors_to_select = num_sectors_to_select
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.regime_sma_period = regime_sma_period
        self.max_entry_rsi = max_entry_rsi
        
        self.weights = weights or {
            "momentum": 0.5,
            "rsi": 0.2,
            "volume_trend": 0.3,
        }
        self.provider = data_provider

        # [New] Universe Selection Logic
        if isinstance(universe, dict):
            self.sector_list = universe
        elif universe == "broad":
            self.sector_list = GICS_SECTOR_LIST
        elif universe == "sub_sector":
            self.sector_list = SUB_SECTOR_LIST
        else:
            # Default fallback
            self.sector_list = SUB_SECTOR_LIST

        self.rsi_field = f"close_RSI_{self.rsi_period}"
        self.atr_field = f"ATRr_{self.atr_period}"
        self.safe_haven_symbol = safe_haven_symbol
        self.benchmark_symbol = benchmark_symbol

    def get_name(self) -> str:
        return "SectorRotation"

    def get_lookback_window(self) -> int:
        return max(self.regime_sma_period + 20, self.look_back_days + 20)

    def _detect_market_regime(self) -> Dict[str, Any]:
        # Use self.benchmark_symbol instead of global constant
        fetch_len = self.regime_sma_period + 10
        benchmark_symbol_candles = self.provider.get_price_data(self.benchmark_symbol, "1d", fetch_len)
        
        if not benchmark_symbol_candles or len(benchmark_symbol_candles) < self.regime_sma_period:
            logger.warning(f"Insufficient data for {self.benchmark_symbol}. Defaulting to SHORT.")
            return {"long_regime": False, "sma_val": 0, "current_price": 0}

        benchmark_symbol_candles_closes = [float(getattr(c, "close")) for c in benchmark_symbol_candles]
        current_price = benchmark_symbol_candles_closes[-1]
        sma_val = np.mean(benchmark_symbol_candles_closes[-self.regime_sma_period:])
        
        long_regime = current_price > sma_val

        return {
            "long_regime": long_regime,
            "current_price": current_price,
            "sma_val": sma_val
        }

    def _compute_momentum(self, closes: List[float], lookback: int) -> float:
        if len(closes) < lookback:
            return 0.0
        return (closes[-1] / closes[-lookback]) - 1

    def generate_signal(self, symbol: str = None, candles: List[Any] = None) -> SignalModel:
        logger.info("🔍 Generating Sector Rotation signal...")
        
        etf_indicators: Dict[str, Indicators] = {}
        
        # 1. Market Regime
        regime = self._detect_market_regime()
        long_regime = regime["long_regime"]
        
        # 2. Collect Data (Using self.sector_list)
        valid_sectors = []
        date = None
        
        for sector_name, etf in self.sector_list.items():
            _candles = self.provider.get_price_data(etf, interval="1d", lookback=self.get_lookback_window())
            
            if not _candles or len(_candles) < self.look_back_days:
                continue

            closes = [float(getattr(c, "close")) for c in _candles]
            vols = [float(getattr(c, "volume")) for c in _candles]
            price = closes[-1]
            date = getattr(_candles[-1], "date")

            rsi_series = self.provider.get_indicator("rsi", _candles, {"length": self.rsi_period})
            atr_series = self.provider.get_indicator("atr", _candles, {"length": self.atr_period})
            
            curr_rsi = getattr(rsi_series[-1], self.rsi_field, 50) if rsi_series else 50
            curr_atr = getattr(atr_series[-1], self.atr_field, 0) if atr_series else 0
            
            volatility = (curr_atr / price) if price > 0 else 0.01
            mom = self._compute_momentum(closes, self.look_back_days)
            
            avg_vol_20 = np.mean(vols[-20:]) if len(vols) >= 20 else 1
            curr_vol_3d = np.mean(vols[-3:]) if len(vols) >= 3 else vols[-1]
            vol_trend = curr_vol_3d / avg_vol_20 if avg_vol_20 > 0 else 1.0
            avg_vol_long = np.mean(vols[-self.look_back_days:])

            etf_indicators[etf] = Indicators(
                rsi=curr_rsi,
                volatility=volatility,
                momentum=mom,
                avg_volume=avg_vol_long,
                volume_trend=vol_trend
            )
            valid_sectors.append(etf)

        if not valid_sectors:
            return SignalModel(symbol="CASH", strategy=self.get_name(), signal="hold", reason="No valid sector data")

        # 3. Compute Scores
        df = pd.DataFrame({etf: ind.model_dump() for etf, ind in etf_indicators.items()}).T
        df = df.fillna(df.mean())
        
        z_mom = zscore(df['momentum'])
        z_rsi = zscore(df['rsi'])
        z_vol = zscore(df['volume_trend'])
        
        df['composite_score'] = (
            (z_mom * self.weights['momentum']) +
            (z_rsi * self.weights['rsi']) +
            (z_vol * self.weights['volume_trend'])
        )

        # 4. Filter & Select
        min_rsi = 40 if long_regime else 50
        max_vol_percentile = 80 if long_regime else 50
        max_vol_val = np.percentile(df['volatility'], max_vol_percentile)
        
        candidates = df[
            (df['rsi'] > min_rsi) & 
            (df['rsi'] < self.max_entry_rsi) & 
            (df['volatility'] <= max_vol_val) &
            (df['momentum'] > 0)
        ]
        
        top_sectors = candidates.sort_values(by='composite_score', ascending=False).head(self.num_sectors_to_select)
        
        selected_symbols = []
        allocations = {}
        reason = ""
        
        if top_sectors.empty:
            # Use self.safe_haven_symbol
            selected_symbols = [self.safe_haven_symbol]
            allocations = {self.safe_haven_symbol: 1.0}
            reason = f"Safety Mode: No sectors met criteria (Regime Long: {long_regime})"
        else:
            selected_symbols = top_sectors.index.tolist()
            inv_vol = 1.0 / top_sectors['volatility']
            allocations = (inv_vol / inv_vol.sum()).to_dict()
            
            for k, v in allocations.items():
                if v > 0.5: allocations[k] = 0.5
            
            total_w = sum(allocations.values())
            allocations = {k: v/total_w for k, v in allocations.items()}
            
            reason = f"Top Sectors: {','.join(selected_symbols)} (Regime Long: {long_regime})"

        details = {
            "regime": "Long" if long_regime else "Short",
            f"{self.benchmark_symbol}_sma": regime.get("sma_val"),
            "allocations": allocations,
            "all_scores": df['composite_score'].to_dict()
        }

        return SignalModel(
            symbol=",".join(selected_symbols),
            strategy=self.get_name(),
            signal="rebalance",
            date=date,
            confidence=1.0,
            reason=reason,
            details=details,
        )

def make_sector_rotation_presets(preset: SectorRotationPreset) -> Dict[str, Any]:
    """
    Returns the configuration for a specific Sector Rotation preset.
    
    Args:
        preset: 'swing' (Sub-sectors, faster) or 'position' (Broad sectors, slower).
    """
    
    if preset == "swing":
        return {
            "universe": "sub_sector",            # Use Heated Sub-Sectors
            "look_back_days": 20,                
            "regime_sma_period": 50,
            "num_sectors_to_select": 3,
            "weights": {"momentum": 0.6, "rsi": 0.1, "volume_trend": 0.3},
            "max_entry_rsi": 85.0,
            "safe_haven_symbol": "SHY",  # Cash equivalent for short-term safety
            "benchmark_symbol": "SPY"
        }
    
    elif preset == "position":
        return {
            "universe": "broad",                 # Use GICS Sectors
            "look_back_days": 126,               
            "regime_sma_period": 200,            
            "num_sectors_to_select": 2,          
            "weights": {"momentum": 0.7, "rsi": 0.1, "volume_trend": 0.2},
            "max_entry_rsi": 95.0,
            "safe_haven_symbol": "IEF",  # 7-10 Year Treasury for hedging
            "benchmark_symbol": "SPY"
        }

    else:
        raise ValueError(f"Unknown preset: {preset}")
