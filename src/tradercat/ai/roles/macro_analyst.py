"""MacroAnalystRole — P2: Global macro regime analysis via LLM.

Combines Identity system prompt + macro analysis instructions, then calls LLM
with compressed ETF/index signal data to produce the global regime report.

Token optimization:
  - Only sends global (ETF/index) signals, not per-stock signals
  - Compresses OHLCV to essential fields (close, volume, vol_zscore, bar_change_pct)
  - Strips indicator bloat — keeps only key metrics per strategy
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

# Keys to keep from OHLCV to reduce token count
_OHLCV_ESSENTIAL = {"close", "volume", "avg_volume", "rel_volume", "vol_zscore", "bar_change_pct"}

# Keys to keep from indicators (top-level only — strategy-specific essentials)
_INDICATOR_ESSENTIAL = {
    "rsi", "adx", "macd_histogram", "macd_signal", "macd_line",
    "ema_9", "ema_21", "sma_50", "sma_200",
    "bb_upper", "bb_lower", "bb_width", "bb_squeeze",
    "atr_pct", "obv_slope", "vwap", "supertrend_direction",
    "trend_direction", "trend_strength",
}


def _compress_signal(sig: Dict[str, Any]) -> Dict[str, Any]:
    """Strip a signal dict to essential fields for macro analysis."""
    ohlcv = sig.get("ohlcv") or {}
    compressed_ohlcv = {k: v for k, v in ohlcv.items() if k in _OHLCV_ESSENTIAL}

    indicators = sig.get("indicators") or {}
    compressed_indicators = {k: v for k, v in indicators.items() if k in _INDICATOR_ESSENTIAL}

    return {
        "symbol": sig.get("symbol"),
        "strategy": sig.get("strategy"),
        "signal": sig.get("signal"),
        "confidence": sig.get("confidence"),
        "reason": sig.get("reason"),
        "ohlcv": compressed_ohlcv,
        "indicators": compressed_indicators,
    }


class MacroAnalystRole(AIRole):
    """
    Macro Analyst Role — P2: global regime classification.

    Uses the options_strategist identity (or configurable) combined with
    macro analysis instructions to classify the current market regime.
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

    @property
    def role_type(self) -> RoleType:
        return RoleType.ANALYSIS

    def _compose_system_prompt(self) -> str:
        identity_prompt = self.identity.get_system_prompt()
        return f"{identity_prompt}\n\n---\n\n{MACRO_ANALYSIS_SYSTEM}"

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

        # --- Token optimization: compress signals ---
        compressed = [_compress_signal(s) for s in signals_data]
        signals_json = json.dumps(compressed, indent=2, default=str)

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

        content = await self.llm.generate_thought(
            prompt=user_prompt,
            model_id=self.model_id,
            system_prompt=system_prompt,
            api_key=self.api_key,
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
