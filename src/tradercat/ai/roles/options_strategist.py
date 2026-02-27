"""OptionsStrategistRole — P3: Per-symbol options execution plans via LLM.

Combines Identity system prompt + symbol analysis instructions, then calls LLM
with batched symbol data + compressed macro regime context to produce
per-symbol execution plans.

Token optimization:
  - Sends only "Section 4: Downstream Filters" from P2 (not full markdown)
  - OHLCV compressed to essential fields
  - Indicators de-duplicated: shared OHLCV once, per-strategy indicators only
"""
import json
import re
from datetime import date
from typing import List, Dict, Any, Optional

from tradercat.ai.roles.base import AIRole, RoleType, RoleOutput
from tradercat.ai.roles.identity import IdentityRole
from tradercat.ai.providers.llm_interface import LLMProvider
from tradercat.ai.prompts.analysis.symbol_analysis import (
    SYSTEM_PROMPT as SYMBOL_ANALYSIS_SYSTEM,
    USER_PROMPT_TEMPLATE as SYMBOL_ANALYSIS_USER,
)
from tradercat.logger import get_logger

logger = get_logger(__name__)

# Essential OHLCV keys for per-symbol analysis
_OHLCV_ESSENTIAL = {
    "open", "high", "low", "close", "volume",
    "avg_volume", "rel_volume", "vol_zscore", "bar_change_pct",
}


def _compress_ohlcv(ohlcv: Dict[str, Any]) -> Dict[str, Any]:
    """Strip OHLCV to essential fields."""
    if not ohlcv:
        return {}
    return {k: v for k, v in ohlcv.items() if k in _OHLCV_ESSENTIAL}


def extract_downstream_filters(regime_md: str) -> str:
    """
    Extract Section 4 (Downstream Filters) + regime header from P2 markdown.
    Falls back to the full markdown (truncated) if section not found.
    
    This dramatically reduces token count when passing P2 context to P3.
    """
    if not regime_md:
        return ""

    # Try to extract the regime classification line
    regime_line = ""
    m = re.search(
        r"\*\*Regime\*\*:\s*(.+?)$",
        regime_md,
        re.MULTILINE,
    )
    if m:
        regime_line = f"**Regime**: {m.group(1).strip()}\n"

    score_line = ""
    m = re.search(
        r"\*\*Regime Score\*\*:\s*(.+?)$",
        regime_md,
        re.MULTILINE,
    )
    if m:
        score_line = f"**Regime Score**: {m.group(1).strip()}\n"

    # Extract Section 4: Downstream Filters
    m = re.search(
        r"(##\s*4\.?\s*Downstream Filters.*?)(?=\n##\s|\Z)",
        regime_md,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        filters_section = m.group(1).strip()
        return f"{regime_line}{score_line}\n{filters_section}"

    # Fallback: return first 1500 chars (enough for regime + filters)
    truncated = regime_md[:1500]
    if len(regime_md) > 1500:
        truncated += "\n\n[... regime report truncated for token efficiency ...]"
    return truncated


def build_batch_payload(
    batch_symbols: List[str],
    signals_by_symbol: Dict[str, List[Dict[str, Any]]],
    historical_by_symbol: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> str:
    """
    Build a token-efficient JSON payload for a batch of symbols.

    Deduplicates OHLCV (shared across strategies for the same symbol),
    compresses to essential fields, and attaches historical signal summaries.
    """
    historical_by_symbol = historical_by_symbol or {}

    batch_data = []
    for symbol in batch_symbols:
        symbol_signals = signals_by_symbol.get(symbol, [])

        # Extract shared OHLCV from the first signal (same for all strategies)
        ohlcv: Dict[str, Any] = {}
        for sig in symbol_signals:
            if sig.get("ohlcv"):
                ohlcv = _compress_ohlcv(sig["ohlcv"])
                break

        # Build per-strategy entries with signal + indicators only
        strategies = []
        for sig in symbol_signals:
            strategies.append({
                "strategy": sig.get("strategy"),
                "signal": sig.get("signal"),
                "confidence": sig.get("confidence"),
                "reason": sig.get("reason"),
                "indicators": sig.get("indicators", {}),
            })

        # Compressed historical signals (direction + confidence only)
        hist_signals = historical_by_symbol.get(symbol, [])
        hist_summary = []
        for h in hist_signals:
            hist_summary.append({
                "date": str(h.get("run_date", "")),
                "strategy": h.get("strategy"),
                "signal": h.get("signal"),
                "confidence": h.get("confidence"),
            })

        entry: Dict[str, Any] = {
            "symbol": symbol,
            "ohlcv": ohlcv,
            "strategies": strategies,
        }
        if hist_summary:
            entry["historical_signals"] = hist_summary

        batch_data.append(entry)

    return json.dumps(batch_data, indent=2, default=str)


class OptionsStrategistRole(AIRole):
    """
    Options Strategist Role — P3: per-symbol execution plans.

    Uses the options_strategist identity + symbol analysis instructions
    to produce audited options trading plans for each symbol in a batch.
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
        return f"{identity_prompt}\n\n---\n\n{SYMBOL_ANALYSIS_SYSTEM}"

    async def analyze_batch(
        self,
        symbol_data_json: str,
        global_context: str,
    ) -> RoleOutput:
        """
        Analyze a batch of symbols with compressed global context.

        Args:
            symbol_data_json: JSON string from build_batch_payload().
            global_context: Compressed regime context (from extract_downstream_filters).

        Returns:
            RoleOutput containing combined markdown with ## SYMBOL headers.
        """
        system_prompt = self._compose_system_prompt()

        user_prompt = SYMBOL_ANALYSIS_USER.format(
            global_context=global_context,
            symbol_data_json=symbol_data_json,
        )

        logger.info(
            f"P3 OptionsStrategist: Batch analysis "
            f"(context={len(global_context)} chars, data={len(symbol_data_json)} chars, "
            f"identity={self.identity.identity_key}, model={self.model_id})"
        )
        logger.debug(f"P3 system_prompt length: {len(system_prompt)}")
        logger.debug(f"P3 user_prompt length: {len(user_prompt)}")

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
            metadata={"analysis_type": "symbol_batch"},
        )

    async def execute(self, **kwargs) -> RoleOutput:
        return await self.analyze_batch(
            symbol_data_json=kwargs["symbol_data_json"],
            global_context=kwargs.get("global_context", ""),
        )
