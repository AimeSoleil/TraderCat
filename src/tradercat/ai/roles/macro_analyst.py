"""MacroAnalystRole — P2: Global macro regime analysis via LLM.

Combines macro_analyst Identity + macro analysis instructions, then calls LLM
with compressed ETF/index signal data to produce the global regime report.

Token optimization:
  - Only sends global (ETF/index) signals, not per-stock signals
  - OHLCV compressed to essential fields (close, volume, vol_zscore, bar_change_pct)
  - Shared indicators hoisted to symbol-level; per-strategy has only unique keys
  - Hold signals stripped to strategy+signal (no indicators/reason)
  - Compact JSON serialization (no indent, minimal separators)
"""
import json
from datetime import date
from typing import List, Dict, Any, Optional

from tradercat.ai.roles.base import AIRole, RoleType, RoleOutput
from tradercat.ai.roles.identity import IdentityRole
from tradercat.ai.providers.llm_interface import LLMProvider
from tradercat.ai.prompts.analysis.macro_analysis import (
    SYSTEM_PROMPT as MACRO_ANALYSIS_SYSTEM,
    USER_PROMPT_TEMPLATE as MACRO_ANALYSIS_USER,
)
from tradercat.logger import get_logger

logger = get_logger(__name__)

# Keys to keep from OHLCV — exact matches + prefix matches for suffixed keys
_OHLCV_EXACT = {"close", "volume", "bar_change_pct"}
_OHLCV_PREFIXES = ("avg_volume", "rel_volume", "vol_zscore")

# Keys to keep from indicators — actual keys produced by pipeline strategies
_INDICATOR_ESSENTIAL = {
    # Trend & momentum (shared across most strategies)
    "adx_14", "rsi_14", "atr_14", "atr_pct",
    "macd_hist_12_26_9",
    "ema_fast_13", "ema_slow_34", "ema_spread_pct",
    # Bollinger bands (BBandsBreakout / BBandsReversal)
    "bandwidth_20", "pct_b_20", "squeeze",
    # Momentum strategy
    "mom_score_risk_adj", "daily_trend_up", "ht_trend_up",
}


def _compress_ohlcv(ohlcv: Dict[str, Any]) -> Dict[str, Any]:
    """Strip OHLCV to essential fields for macro analysis."""
    if not ohlcv:
        return {}
    return {
        k: v for k, v in ohlcv.items()
        if k in _OHLCV_EXACT or k.startswith(_OHLCV_PREFIXES)
    }


def _filter_indicators(indicators: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only essential indicators for macro analysis."""
    if not indicators:
        return {}
    return {k: v for k, v in indicators.items() if k in _INDICATOR_ESSENTIAL}


def build_p2_payload(signals_data: List[Dict[str, Any]]) -> str:
    """
    Build token-efficient JSON payload for P2 macro analysis.

    Groups signals by symbol. Per symbol:
      - Shared OHLCV extracted once
      - Shared indicators hoisted to symbol-level
      - Hold signals stripped to strategy+signal only
      - Compact JSON (no indent)
    """
    # Group signals by symbol
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for sig in signals_data:
        sym = sig.get("symbol", "UNKNOWN")
        by_symbol.setdefault(sym, []).append(sig)

    batch_data = []
    for symbol, signals in by_symbol.items():
        # Extract shared OHLCV from the first signal
        ohlcv: Dict[str, Any] = {}
        for sig in signals:
            if sig.get("ohlcv"):
                ohlcv = _compress_ohlcv(sig["ohlcv"])
                break

        # Collect and filter all indicator dicts
        all_indicator_dicts = [
            _filter_indicators(sig.get("indicators") or {}) for sig in signals
        ]

        # Find shared indicators (same value across 2+ strategies)
        shared_indicators: Dict[str, Any] = {}
        if len(all_indicator_dicts) >= 2:
            key_values: Dict[str, list] = {}
            for ind_dict in all_indicator_dicts:
                for k, v in ind_dict.items():
                    key_values.setdefault(k, []).append(v)
            for k, values in key_values.items():
                if len(values) >= 2:
                    first = str(values[0])
                    if all(str(v) == first for v in values):
                        shared_indicators[k] = values[0]

        # Build per-strategy entries
        strategies = []
        for i, sig in enumerate(signals):
            sig_signal = (sig.get("signal") or "").lower()

            # Hold signals → strip indicators
            if sig_signal == "hold":
                strategies.append({
                    "strategy": sig.get("strategy"),
                    "signal": sig_signal,
                    "confidence": sig.get("confidence"),
                })
                continue

            # Unique indicators (not in shared)
            raw_indicators = all_indicator_dicts[i] if i < len(all_indicator_dicts) else {}
            unique_indicators = {
                k: v for k, v in raw_indicators.items()
                if k not in shared_indicators
            } if shared_indicators else raw_indicators

            entry = {
                "strategy": sig.get("strategy"),
                "signal": sig_signal,
                "confidence": sig.get("confidence"),
                "reason": sig.get("reason"),
            }
            if unique_indicators:
                entry["indicators"] = unique_indicators
            strategies.append(entry)

        symbol_entry: Dict[str, Any] = {
            "symbol": symbol,
            "ohlcv": ohlcv,
        }
        if shared_indicators:
            symbol_entry["shared_indicators"] = shared_indicators
        symbol_entry["strategies"] = strategies

        batch_data.append(symbol_entry)

    # Compact JSON
    return json.dumps(batch_data, separators=(",", ":"), default=str)


class MacroAnalystRole(AIRole):
    """
    Macro Analyst Role — P2: global regime classification.

    Uses the macro_analyst identity combined with macro analysis instructions
    to classify the current market regime from ETF/index signals.
    """

    def __init__(
        self,
        llm: LLMProvider,
        identity: IdentityRole,
        model_id: str = "claude-opus-4.6",
        api_key: Optional[str] = None,
    ):
        self.llm = llm
        self.identity = identity
        self.model_id = model_id
        self.api_key = api_key
        self._system_prompt_cache: Optional[str] = None

    @property
    def role_type(self) -> RoleType:
        return RoleType.ANALYSIS

    def _compose_system_prompt(self) -> str:
        if self._system_prompt_cache is None:
            identity_prompt = self.identity.get_system_prompt()
            self._system_prompt_cache = f"{identity_prompt}\n\n---\n\n{MACRO_ANALYSIS_SYSTEM}"
        return self._system_prompt_cache

    async def analyze(
        self,
        run_date: str,
        signals_data: List[Dict[str, Any]],
    ) -> RoleOutput:
        """
        Perform global macro regime analysis.

        Args:
            run_date: The analysis date string.
            signals_data: List of ETF/index signal dicts (will be compressed).

        Returns:
            RoleOutput with the regime report markdown.
        """
        system_prompt = self._compose_system_prompt()

        # --- Token optimization: build compressed payload ---
        signals_json = build_p2_payload(signals_data)

        user_prompt = MACRO_ANALYSIS_USER.format(
            run_date=run_date,
            signals_json=signals_json,
        )

        logger.info(
            f"P2 MacroAnalyst: Starting global analysis for {run_date} "
            f"({len(signals_data)} signals → {len(signals_json)} chars, "
            f"identity={self.identity.identity_key}, model={self.model_id})"
        )
        logger.debug(f"P2 system_prompt length: {len(system_prompt)}")
        logger.debug(f"P2 user_prompt length: {len(user_prompt)}")

        from tradercat.config import settings

        content = await self.llm.generate_thought(
            prompt=user_prompt,
            model_id=self.model_id,
            system_prompt=system_prompt,
            api_key=self.api_key,
            max_tokens=settings.llm_max_tokens_p2,
        )

        return RoleOutput(
            role=RoleType.ANALYSIS,
            identity=self.identity.identity_key,
            content=content,
            model_used=self.model_id,
            metadata={
                "analysis_type": "macro",
                "run_date": run_date,
                "signal_count": len(signals_data),
                "compressed_chars": len(signals_json),
            },
        )

    async def execute(self, **kwargs) -> RoleOutput:
        return await self.analyze(
            run_date=kwargs["run_date"],
            signals_data=kwargs["signals_data"],
        )
