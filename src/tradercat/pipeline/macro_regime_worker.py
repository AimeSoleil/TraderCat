"""Macro regime worker for pipeline P2 — MacroAnalystRole.

P2 produces the global market regime report (one per run_date).
Uses MacroAnalystRole with the macro_analyst identity to classify
the current regime from ETF/index signals.

Token optimization:
  - Only sends global-symbol signals (ETFs/indices).
  - Shared indicators hoisted to symbol-level; hold signals stripped.
  - Compact JSON (no indent, minimal separators).
"""
import asyncio
import json
import re
from datetime import date
from typing import List, Dict, Any, Optional
from uuid import UUID

from tradercat.logger import get_logger
from tradercat.config import settings
from tradercat.ai.providers.llm_interface import LLMProvider
from tradercat.ai.roles.identity import IdentityRole
from tradercat.ai.roles.macro_analyst import MacroAnalystRole

logger = get_logger(__name__)


def _json_safe(obj: Any) -> Any:
    """Round-trip through JSON so every value is JSON-serializable."""
    return json.loads(json.dumps(obj, default=str))


def _get_llm_provider(model_id: str = None):
    from tradercat.ai.llm_provider_factory import LLMFactory
    model_id = model_id or settings.default_llm_model
    provider_key = settings.default_llm_provider
    provider, resolved_model = LLMFactory.create_provider(f"{provider_key}_{model_id}")
    return provider, resolved_model


# ─── JSON block extraction cache ────────────────────────────────

_p2_json_cache: Dict[int, Optional[Dict[str, Any]]] = {}


def _extract_p2_json_block(content: str) -> Optional[Dict[str, Any]]:
    """Extract the structured JSON block from P2 output (new hybrid format).

    The new P2 prompt outputs a JSON object in ```json fences followed by markdown.
    This function extracts and caches the JSON block.
    Cache key is content hash to avoid re-parsing for multiple field extractions.
    """
    cache_key = hash(content)
    if cache_key in _p2_json_cache:
        return _p2_json_cache[cache_key]

    result = None
    # Try code-fenced JSON object
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict):
                result = data
        except json.JSONDecodeError:
            pass

    _p2_json_cache[cache_key] = result
    return result


def _extract_regime_label(content_md: str) -> Optional[str]:
    """Extract regime label from the report output.

    Tries structured JSON block first (new format), falls back to markdown regex.
    """
    # Try JSON block first (new P2 output format)
    json_data = _extract_p2_json_block(content_md)
    if json_data:
        label = json_data.get("regime_label", "")
        name = json_data.get("regime_name", "")
        if label and name:
            return f"{label} — {name}"[:80]
        if label:
            return label[:80]

    # Fallback: regex from markdown
    m = re.search(r"\*\*Regime\*\*:\s*(.+?)$", content_md, re.MULTILINE)
    if m:
        return m.group(1).strip()[:80]
    return None


def _extract_regime_score(content_md: str) -> Optional[float]:
    """Extract regime score from the report output.

    Tries structured JSON block first (new format), falls back to markdown regex.
    """
    # Try JSON block first
    json_data = _extract_p2_json_block(content_md)
    if json_data and "regime_score" in json_data:
        try:
            return float(json_data["regime_score"])
        except (ValueError, TypeError):
            pass

    # Fallback: regex from markdown
    m = re.search(r"\*\*Regime Score\*\*:\s*([+-]?\d+(?:\.\d+)?)", content_md)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _extract_downstream_filters_json(content_md: str) -> Optional[Dict[str, Any]]:
    """Best-effort extraction of downstream filters as structured data.

    Tries structured JSON block first (new format), falls back to Section 4 regex.
    """
    # Try JSON block first
    json_data = _extract_p2_json_block(content_md)
    if json_data and "downstream_filters" in json_data:
        filters = json_data["downstream_filters"]
        if isinstance(filters, dict) and filters:
            return filters

    # Fallback: regex from markdown Section 4
    m = re.search(
        r"##\s*4\.?\s*Downstream Filters.*?\n(.*?)(?=\n##\s|\Z)",
        content_md,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None

    text = m.group(1)
    filters: Dict[str, Any] = {}

    for line in text.splitlines():
        line = line.strip().lstrip("-").strip()
        if ":" not in line:
            continue
        key_raw, _, val = line.partition(":")
        # Clean markdown bold markers
        key = re.sub(r"\*+", "", key_raw).strip().lower().replace(" ", "_")
        val = val.strip()
        if key and val:
            filters[key] = val

    return filters if filters else None


class MacroRegimeWorker:
    """Worker for generating the macro regime context (P2)."""

    # Fixed identity for P2 — always "macro_analyst"
    _P2_IDENTITY = "macro_analyst"

    def __init__(
        self,
        max_retries: int | None = None,
        model_id: str | None = None,
        api_key: str | None = None,
    ):
        self.max_retries = max_retries if max_retries is not None else settings.pipeline_llm_max_retries
        self.model_id = model_id or settings.default_llm_model
        self.api_key = api_key

        self._provider: Optional[LLMProvider] = None
        self._analyst: Optional[MacroAnalystRole] = None

    def _ensure_roles(self):
        if self._analyst is not None:
            return
        try:
            self._provider, self.model_id = _get_llm_provider(self.model_id)
        except Exception as e:
            logger.warning(f"P2: Failed to init LLM provider: {e}. Will use fallback.")
            self._provider = None
            return
        identity = IdentityRole(self._P2_IDENTITY)
        self._analyst = MacroAnalystRole(self._provider, identity, self.model_id, api_key=self.api_key)

    async def generate(
        self,
        run_date: date,
        etf_signals: List[Dict[str, Any]],
        pipeline_run_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate macro regime context record.

        Returns a dict ready for DB insert/upsert, or None on failure.
        """
        self._ensure_roles()

        logger.info(
            f"P2: Generating macro regime context for {run_date} "
            f"({len(etf_signals)} ETF signals, identity={self._P2_IDENTITY}, model={self.model_id})"
        )

        for attempt in range(self.max_retries + 1):
            try:
                if self._analyst:
                    result = await self._analyst.analyze(
                        run_date=str(run_date),
                        signals_data=etf_signals,
                    )
                    content = result.content
                else:
                    content = self._placeholder(run_date, etf_signals)

                return {
                    "run_date": run_date,
                    "regime_label": _extract_regime_label(content),
                    "regime_score": _extract_regime_score(content),
                    "content_md": content,
                    "downstream_filters": _extract_downstream_filters_json(content),
                    "model_used": self.model_id,
                    "identity_used": self._P2_IDENTITY,
                    "input_context": _json_safe({"etf_signals": etf_signals}),
                    "pipeline_run_id": pipeline_run_id,
                }

            except Exception as e:
                if attempt < self.max_retries:
                    logger.warning(f"P2: Retry {attempt + 1}/{self.max_retries}: {e}")
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"P2: Failed after {self.max_retries + 1} attempts: {e}")
                    return None

        return None

    @staticmethod
    def _placeholder(run_date: date, etf_signals: List[Dict[str, Any]]) -> str:
        symbols = set(s.get("symbol", "?") for s in etf_signals)
        report = f"# Global Market Regime Report — {run_date}\n\n"
        report += "## 1. Regime Classification\n"
        report += "- **Regime**: YELLOW — Choppy/Transitional\n"
        report += "- **Regime Score**: 0.0\n"
        report += "- **Regime Trend**: Stable\n"
        report += f"- **Key Evidence**: {len(etf_signals)} signals from {', '.join(sorted(symbols))}\n"
        report += "- **Override Applied**: None\n\n"
        report += "## 2. Sector Rotation Map\n\n"
        report += f"Based on {len(etf_signals)} ETF signals — no LLM analysis available.\n\n"
        report += "- **Favored Sectors**: None\n"
        report += "- **Avoid Sectors**: None\n\n"
        report += "## 3. Cross-Asset Signals\n"
        report += "- **Risk Appetite**: Mixed\n"
        report += "- **Volatility Trend**: Stable\n\n"
        report += (
            "## 4. Downstream Filters (For Per-Symbol Analysis)\n"
            "- **Directional Bias**: BOTH\n"
            "- **Confidence Floor**: 0.65\n"
            "- **Favored Sectors**: None\n"
            "- **Avoid Sectors**: None\n"
            "- **Risk Modifier**: 0.75x\n"
            "- **Cash Reserve**: 30%\n"
            "- **Special Conditions**: Defined-risk only (LLM unavailable)\n"
        )
        report += "\n---\n*Placeholder — LLM not available*\n"
        return report


async def generate_macro_regime_p2(
    run_date: date,
    all_signals: List[Dict[str, Any]],
    pipeline_run_id: UUID,
    global_symbols: List[str],
    api_key: str | None = None,
) -> Optional[Dict[str, Any]]:
    """
    P2 entry point: generate macro regime context from global-symbol signals.
    """
    etf_signals = [s for s in all_signals if s["symbol"] in global_symbols]

    logger.info(
        f"P2: {len(etf_signals)} ETF signals from {len(global_symbols)} global symbols"
    )

    worker = MacroRegimeWorker(api_key=api_key)
    return await worker.generate(
        run_date=run_date,
        etf_signals=etf_signals,
        pipeline_run_id=pipeline_run_id,
    )
