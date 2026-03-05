"""OptionsStrategistRole — P3: Per-symbol options execution plans via LLM.

Tier 3 architecture:
  P3a (gate audit) — large batch → JSON verdict per symbol
  P3b (execution plans) — approved symbols only → JSON execution plan

Both phases use the options_strategist identity but different system prompts.

Token optimization:
  - P3a: batch=20+ symbols, compact verdict output (~50 tokens/symbol)
  - P3b: only approved symbols, batch=3, no gate re-evaluation
  - Sends only "Section 4: Downstream Filters" from P2
  - OHLCV compressed to essential fields
  - Indicators de-duplicated: shared across strategies hoisted to symbol-level
  - Hold signals stripped to strategy+signal only
  - Historical OHLCV de-duplicated: one per symbol-date
  - Compact JSON serialization
"""
import json
import re
from typing import List, Dict, Any, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

from tradercat.ai.roles.base import AIRole, RoleType, RoleOutput
from tradercat.ai.roles.identity import IdentityRole
from tradercat.ai.providers.llm_interface import LLMProvider
from tradercat.ai.prompts.analysis.gate_audit import (
    SYSTEM_PROMPT as GATE_AUDIT_SYSTEM,
    USER_PROMPT_TEMPLATE as GATE_AUDIT_USER,
)
from tradercat.ai.prompts.analysis.execution_plan_prompt import (
    SYSTEM_PROMPT as EXEC_PLAN_SYSTEM,
    USER_PROMPT_TEMPLATE as EXEC_PLAN_USER,
)
from tradercat.logger import get_logger

logger = get_logger(__name__)

# Essential OHLCV keys — exact matches + prefix matches for suffixed keys
# Strategies produce avg_volume_20, rel_volume_20, vol_zscore_20 etc.
_OHLCV_EXACT = {
    "open", "high", "low", "close", "volume", "bar_change_pct",
}
_OHLCV_PREFIXES = ("avg_volume", "rel_volume", "vol_zscore")


def _compress_ohlcv(ohlcv: Dict[str, Any]) -> Dict[str, Any]:
    """Strip OHLCV to essential fields."""
    if not ohlcv:
        return {}
    return {
        k: v for k, v in ohlcv.items()
        if k in _OHLCV_EXACT or k.startswith(_OHLCV_PREFIXES)
    }


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

    Token optimizations:
      1a. Indicators shared across strategies are hoisted to symbol-level
          `shared_indicators`; per-strategy `indicators` contains only unique keys.
      1b. Historical OHLCV de-duplicated: one shared `ohlcv` per symbol-date,
          strategies become compact list of (strategy, signal, confidence).
      1c. Hold signals stripped of indicators — only strategy name + signal kept.
      1d. Compact JSON serialization (no indent, minimal separators).
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

        # ── 1a: Indicator dedup ──
        # Collect all indicator dicts, find keys with identical values across
        # 2+ strategies, hoist them to shared_indicators.
        all_indicator_dicts = [
            sig.get("indicators") or {} for sig in symbol_signals
        ]
        shared_indicators: Dict[str, Any] = {}
        if len(all_indicator_dicts) >= 2:
            # Find keys present in at least 2 dicts with identical values
            from collections import Counter
            key_values: Dict[str, list] = {}
            for ind_dict in all_indicator_dicts:
                for k, v in ind_dict.items():
                    key_values.setdefault(k, []).append(v)
            for k, values in key_values.items():
                if len(values) >= 2:
                    # Check all occurrences have same value (compare as strings
                    # to handle float precision edge cases)
                    first = str(values[0])
                    if all(str(v) == first for v in values):
                        shared_indicators[k] = values[0]

        # ── Build per-strategy entries ──
        strategies = []
        for i, sig in enumerate(symbol_signals):
            sig_signal = (sig.get("signal") or "").lower()

            # 1c: Hold signals → strip indicators, keep only verdict
            if sig_signal == "hold":
                strategies.append({
                    "strategy": sig.get("strategy"),
                    "signal": sig_signal,
                    "confidence": sig.get("confidence"),
                })
                continue

            # Compute unique indicators (not in shared)
            raw_indicators = all_indicator_dicts[i] if i < len(all_indicator_dicts) else {}
            if shared_indicators:
                unique_indicators = {
                    k: v for k, v in raw_indicators.items()
                    if k not in shared_indicators
                }
            else:
                unique_indicators = raw_indicators

            entry = {
                "strategy": sig.get("strategy"),
                "signal": sig_signal,
                "confidence": sig.get("confidence"),
                "reason": sig.get("reason"),
            }
            if unique_indicators:
                entry["indicators"] = unique_indicators
            strategies.append(entry)

        # ── 1b: Historical signal dedup ──
        # Group by date → one shared ohlcv per date, compact strategy list
        hist_signals = historical_by_symbol.get(symbol, [])
        hist_summary: List[Dict[str, Any]] = []

        if hist_signals:
            # Group historical signals by date
            by_date: Dict[str, Dict[str, Any]] = {}
            for h in hist_signals:
                d = str(h.get("run_date", ""))
                if d not in by_date:
                    hist_ohlcv = h.get("ohlcv") or {}
                    by_date[d] = {
                        "date": d,
                        "ohlcv": _compress_ohlcv(hist_ohlcv) if hist_ohlcv else {},
                        "signals": [],
                    }
                by_date[d]["signals"].append({
                    "strategy": h.get("strategy"),
                    "signal": h.get("signal"),
                    "confidence": h.get("confidence"),
                })
            hist_summary = list(by_date.values())

        symbol_entry: Dict[str, Any] = {
            "symbol": symbol,
            "ohlcv": ohlcv,
        }
        if shared_indicators:
            symbol_entry["shared_indicators"] = shared_indicators
        symbol_entry["strategies"] = strategies
        if hist_summary:
            symbol_entry["history"] = hist_summary

        batch_data.append(symbol_entry)

    # 1d: Compact JSON (no indent, minimal separators)
    return json.dumps(batch_data, separators=(",", ":"), default=str)


# ─── JSON parsing helpers ───────────────────────────────────────

def parse_json_output(raw: str) -> List[Dict[str, Any]]:
    """Extract and parse a JSON array from LLM output.

    Handles:
      - Raw JSON array
      - JSON wrapped in ```json ... ``` code fences
      - JSON with preamble/postamble text
    """
    # Try code fence first
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON array
    m = re.search(r"\[\s*\{.*\}\s*\]", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    # Try whole string
    try:
        result = json.loads(raw.strip())
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
    except json.JSONDecodeError:
        pass

    return []


# ─── Pydantic validation schemas ────────────────────────────────


class VerdictTechnicals(BaseModel):
    """Technical indicator snapshot embedded in a P3a verdict."""

    model_config = ConfigDict(extra="allow", coerce_numbers_to_str=False)

    trend_adx: Optional[float] = None
    trend_ema_fast: Optional[float] = None
    trend_ema_slow: Optional[float] = None
    trend_ema_spread_pct: Optional[float] = None
    trend_pct_b: Optional[float] = None
    momentum_rsi: Optional[float] = None
    momentum_macd_hist: Optional[float] = None
    momentum_mom_score: Optional[float] = None
    volume_rel: Optional[float] = None
    volume_zscore: Optional[float] = None
    volume_classification: Optional[str] = None
    volatility_atr_pct: Optional[float] = None
    volatility_bandwidth: Optional[float] = None
    volatility_squeeze: Optional[bool] = None
    key_level_support: Optional[float] = None
    key_level_resistance: Optional[float] = None


class VerdictSchema(BaseModel):
    """P3a verdict output for a single symbol."""

    model_config = ConfigDict(extra="allow")

    symbol: str
    direction: str  # LONG / SHORT / NEUTRAL
    quality: str  # A+ / A / B+ / B / C / REJECT
    rr_estimate: Optional[str] = None
    confluence: Optional[str] = None
    confluence_count: Optional[int] = 0
    setup_type: Optional[str] = None
    historical_trend: Optional[str] = None
    gates: Optional[str] = None
    rejection_reason: Optional[str] = None
    recommended_strategy_type: Optional[str] = None
    technicals: Optional[VerdictTechnicals] = None


class LegSchema(BaseModel):
    """Single option leg within an execution plan."""

    model_config = ConfigDict(extra="allow")

    type: str  # Call / Put
    strike: str
    exp: str
    action: str  # BUY / SELL
    delta: Optional[str] = None
    premium: Optional[str] = None


class ExecutionPlanSchema(BaseModel):
    """P3b execution plan output for a single symbol."""

    model_config = ConfigDict(extra="allow")

    symbol: str
    structure: str
    direction: Optional[str] = None  # credit / debit
    thesis: Optional[str] = None
    rationale: Optional[str] = None
    legs: List[LegSchema] = []
    entry_trigger: Optional[str] = None
    stop_loss: Optional[str] = None
    profit_target: Optional[str] = None
    time_stop: Optional[str] = None
    max_loss: Optional[str] = None
    max_profit: Optional[str] = None
    breakeven: Optional[str] = None
    rr_ratio: Optional[str] = None
    allocation: Optional[str] = None
    dte: Optional[int] = None
    pricing_note: Optional[str] = None


# ─── Validation helpers ─────────────────────────────────────────


def _coerce_numeric_fields(data: Dict[str, Any], float_keys: set) -> Dict[str, Any]:
    """Best-effort: convert string values to float for known numeric fields."""
    coerced: List[str] = []
    for key in float_keys:
        if key in data and data[key] is not None:
            val = data[key]
            if not isinstance(val, (int, float)):
                try:
                    data[key] = float(val)
                    coerced.append(key)
                except (ValueError, TypeError):
                    data[key] = None
                    coerced.append(key)
    if coerced:
        sym = data.get("symbol", "?")
        logger.warning("Coerced fields for %s: %s", sym, ", ".join(coerced))
    return data


_VERDICT_TECHNICALS_FLOAT_KEYS = {
    "trend_adx", "trend_ema_fast", "trend_ema_slow", "trend_ema_spread_pct",
    "trend_pct_b", "momentum_rsi", "momentum_macd_hist", "momentum_mom_score",
    "volume_rel", "volume_zscore", "volatility_atr_pct", "volatility_bandwidth",
    "key_level_support", "key_level_resistance",
}


def validate_verdicts(raw_verdicts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate and sanitize P3a verdict objects.

    Applies best-effort coercion (strings → numbers) and drops items that
    still fail validation.  Returns list of valid dicts.
    """
    valid: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw_verdicts):
        sym = item.get("symbol", f"<index {idx}>")
        try:
            # Coerce technicals sub-dict before validation
            if "technicals" in item and isinstance(item["technicals"], dict):
                item["technicals"] = _coerce_numeric_fields(
                    item["technicals"], _VERDICT_TECHNICALS_FLOAT_KEYS,
                )
            # Coerce confluence_count
            if "confluence_count" in item and item["confluence_count"] is not None:
                try:
                    item["confluence_count"] = int(item["confluence_count"])
                except (ValueError, TypeError):
                    item["confluence_count"] = 0

            model = VerdictSchema(**item)
            valid.append(model.model_dump())
        except ValidationError as exc:
            logger.warning("P3a verdict validation failed for %s: %s", sym, exc)
    logger.info("P3a verdicts validated: %d/%d passed", len(valid), len(raw_verdicts))
    return valid


def validate_execution_plans(raw_plans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate and sanitize P3b execution plan objects.

    Applies best-effort coercion and drops items that still fail validation.
    Returns list of valid dicts.
    """
    valid: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw_plans):
        sym = item.get("symbol", f"<index {idx}>")
        try:
            # Coerce dte to int
            if "dte" in item and item["dte"] is not None:
                try:
                    item["dte"] = int(item["dte"])
                except (ValueError, TypeError):
                    item["dte"] = None

            model = ExecutionPlanSchema(**item)
            valid.append(model.model_dump())
        except ValidationError as exc:
            logger.warning("P3b exec-plan validation failed for %s: %s", sym, exc)
    logger.info("P3b exec-plans validated: %d/%d passed", len(valid), len(raw_plans))
    return valid


# ─── P3b input builder ──────────────────────────────────────────

def build_p3b_payload(
    batch_symbols: List[str],
    signals_by_symbol: Dict[str, List[Dict[str, Any]]],
    verdicts_by_symbol: Dict[str, Dict[str, Any]],
    historical_by_symbol: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> str:
    """Build P3b payload: symbol data + P3a verdicts for approved symbols.

    Each entry includes the verdict from P3a so the execution plan prompt
    knows the direction, quality, setup type, and technical summary.
    """
    historical_by_symbol = historical_by_symbol or {}
    batch_data = []

    for symbol in batch_symbols:
        symbol_signals = signals_by_symbol.get(symbol, [])
        verdict = verdicts_by_symbol.get(symbol, {})

        # OHLCV
        ohlcv: Dict[str, Any] = {}
        for sig in symbol_signals:
            if sig.get("ohlcv"):
                ohlcv = _compress_ohlcv(sig["ohlcv"])
                break

        # Indicator dedup (same as build_batch_payload)
        all_indicator_dicts = [
            sig.get("indicators") or {} for sig in symbol_signals
        ]
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

        # Strategies (compact)
        strategies = []
        for i, sig in enumerate(symbol_signals):
            sig_signal = (sig.get("signal") or "").lower()
            if sig_signal == "hold":
                strategies.append({
                    "strategy": sig.get("strategy"),
                    "signal": sig_signal,
                    "confidence": sig.get("confidence"),
                })
                continue
            raw_ind = all_indicator_dicts[i] if i < len(all_indicator_dicts) else {}
            unique_ind = {k: v for k, v in raw_ind.items() if k not in shared_indicators} if shared_indicators else raw_ind
            entry = {
                "strategy": sig.get("strategy"),
                "signal": sig_signal,
                "confidence": sig.get("confidence"),
                "reason": sig.get("reason"),
            }
            if unique_ind:
                entry["indicators"] = unique_ind
            strategies.append(entry)

        symbol_entry: Dict[str, Any] = {
            "symbol": symbol,
            "verdict": verdict,
            "ohlcv": ohlcv,
        }
        if shared_indicators:
            symbol_entry["shared_indicators"] = shared_indicators
        symbol_entry["strategies"] = strategies
        batch_data.append(symbol_entry)

    return json.dumps(batch_data, separators=(",", ":"), default=str)


# ─── Markdown renderer ──────────────────────────────────────────

def render_plan_markdown(
    verdict: Dict[str, Any],
    execution: Optional[Dict[str, Any]] = None,
) -> str:
    """Render structured P3a verdict + P3b execution into markdown content_md.

    Produces the same format that the frontend MarkdownRenderer expects,
    backward-compatible with the old LLM-generated markdown.
    """
    sym = verdict.get("symbol", "UNKNOWN")
    lines = [f"## {sym} — Analysis Report", ""]

    # ── Signal Assessment ──
    lines.append("### Signal Assessment")
    _md_field(lines, "Direction", verdict.get("direction"))
    _md_field(lines, "Setup Quality", verdict.get("quality"))
    _md_field(lines, "R:R Ratio", verdict.get("rr_estimate"))
    conf = verdict.get("confluence", "")
    count = verdict.get("confluence_count", 1)
    conf_label = f"{conf} | {'×' + str(count) if count > 1 else 'Single'}"
    _md_field(lines, "Confluence", conf_label)
    _md_field(lines, "Setup Type", verdict.get("setup_type"))
    _md_field(lines, "Historical Trend", verdict.get("historical_trend"))
    _md_field(lines, "Gates", verdict.get("gates"))
    if verdict.get("rejection_reason"):
        _md_field(lines, "Rejection Reason", verdict["rejection_reason"])
    lines.append("")

    # ── Technical Summary ──
    tech = verdict.get("technicals") or {}
    if tech:
        lines.append("### Technical Summary")
        # Trend
        trend_parts = []
        if tech.get("trend_adx") is not None:
            trend_parts.append(f"ADX={tech['trend_adx']}")
        if tech.get("trend_ema_fast") is not None:
            trend_parts.append(f"EMA fast={tech['trend_ema_fast']}")
        if tech.get("trend_ema_slow") is not None:
            trend_parts.append(f"EMA slow={tech['trend_ema_slow']}")
        if tech.get("trend_ema_spread_pct") is not None:
            trend_parts.append(f"Spread={tech['trend_ema_spread_pct']}%")
        if tech.get("trend_pct_b") is not None:
            trend_parts.append(f"%B={tech['trend_pct_b']}")
        if trend_parts:
            lines.append(f"- **Trend**: {', '.join(trend_parts)}")
        # Momentum
        mom_parts = []
        if tech.get("momentum_rsi") is not None:
            mom_parts.append(f"RSI={tech['momentum_rsi']}")
        if tech.get("momentum_macd_hist") is not None:
            mom_parts.append(f"MACD hist={tech['momentum_macd_hist']}")
        if tech.get("momentum_mom_score") is not None:
            mom_parts.append(f"Score={tech['momentum_mom_score']}")
        if mom_parts:
            lines.append(f"- **Momentum**: {', '.join(mom_parts)}")
        # Volume
        vol_parts = []
        if tech.get("volume_rel") is not None:
            vol_parts.append(f"Rel={tech['volume_rel']}")
        if tech.get("volume_zscore") is not None:
            vol_parts.append(f"Z={tech['volume_zscore']}")
        if tech.get("volume_classification"):
            vol_parts.append(tech["volume_classification"])
        if vol_parts:
            lines.append(f"- **Volume**: {', '.join(vol_parts)}")
        # Volatility
        vola_parts = []
        if tech.get("volatility_atr_pct") is not None:
            vola_parts.append(f"ATR%={tech['volatility_atr_pct']}")
        if tech.get("volatility_bandwidth") is not None:
            vola_parts.append(f"BW={tech['volatility_bandwidth']}")
        if tech.get("volatility_squeeze") is not None:
            vola_parts.append(f"Squeeze={'Yes' if tech['volatility_squeeze'] else 'No'}")
        if vola_parts:
            lines.append(f"- **Volatility**: {', '.join(vola_parts)}")
        # Key Levels
        level_parts = []
        if tech.get("key_level_support") is not None:
            level_parts.append(f"Support=${tech['key_level_support']}")
        if tech.get("key_level_resistance") is not None:
            level_parts.append(f"Resistance=${tech['key_level_resistance']}")
        if level_parts:
            lines.append(f"- **Key Levels**: {', '.join(level_parts)}")
        lines.append("")

    # ── Execution Plan (only for approved non-REJECT symbols) ──
    direction = (verdict.get("direction") or "").upper()
    quality = (verdict.get("quality") or "").upper()
    if execution and direction != "NEUTRAL" and quality != "REJECT":
        lines.append("### Execution Plan")
        lines.append("")

        # Trade Construction
        lines.append("#### Trade Construction")
        _md_field(lines, "Thesis", execution.get("thesis"))
        _md_field(lines, "Structure", execution.get("structure"))
        _md_field(lines, "Rationale", execution.get("rationale"))
        lines.append("")

        # Leg table
        legs = execution.get("legs", [])
        if legs:
            lines.append("| Leg | Type | Strike | Exp | Action | Δ | Est. Premium |")
            lines.append("|-----|------|--------|-----|--------|---|-------------|")
            for i, leg in enumerate(legs, 1):
                lines.append(
                    f"| {i}   | {leg.get('type', '')} | {leg.get('strike', '')} "
                    f"| {leg.get('exp', '')} | {leg.get('action', '')} "
                    f"| {leg.get('delta', '')} | {leg.get('premium', '')} |"
                )
            lines.append("")

        # Entry / Exit
        lines.append("#### Entry / Exit")
        _md_field(lines, "Entry trigger", execution.get("entry_trigger"))
        _md_field(lines, "Stop loss", execution.get("stop_loss"))
        _md_field(lines, "Profit target", execution.get("profit_target"))
        _md_field(lines, "Time stop", execution.get("time_stop"))
        lines.append("")

        # Risk & Sizing
        lines.append("#### Risk & Sizing")
        _md_field(lines, "Max loss", execution.get("max_loss"))
        _md_field(lines, "Max profit", execution.get("max_profit"))
        _md_field(lines, "Breakeven", execution.get("breakeven"))
        _md_field(lines, "Allocation", execution.get("allocation"))
        _md_field(lines, "R:R", execution.get("rr_ratio") or execution.get("rr"))
        lines.append("")

    return "\n".join(lines)


def _md_field(lines: List[str], label: str, value: Any) -> None:
    """Append a markdown field line if value is truthy."""
    if value is not None and value != "":
        lines.append(f"- **{label}**: {value}")


# ─── P4 structured card builder ─────────────────────────────────

def format_p4_card(structured_data: Dict[str, Any]) -> str:
    """Build a compact P4 trade card directly from structured P3 data.

    This replaces regex-based compress_plan_for_briefing() when structured
    data is available. ~200-300 chars per symbol.
    """
    v = structured_data
    ex = v.get("execution") or {}

    # Line 1: Assessment
    parts = []
    if v.get("direction"):
        parts.append(f"Direction: {v['direction']}")
    if v.get("quality"):
        parts.append(f"Quality: {v['quality']}")
    rr = v.get("rr_estimate") or ex.get("rr", "") or ex.get("rr_ratio", "")
    if rr:
        parts.append(f"R:R: {rr}")
    if v.get("confluence"):
        parts.append(f"Confluence: {v['confluence']}")
    if v.get("setup_type"):
        parts.append(f"Type: {v['setup_type']}")
    if v.get("recommended_strategy_type"):
        parts.append(f"Strategy: {v['recommended_strategy_type']}")

    card_lines = [" | ".join(parts)] if parts else []

    # Rejection shortcut
    if v.get("rejection_reason"):
        card_lines.append(f"REJECTED: {v['rejection_reason']}")
        return "\n".join(card_lines)

    if not ex:
        return "\n".join(card_lines) if card_lines else ""

    # Line 2: Structure + legs
    struct_parts = []
    if ex.get("structure"):
        struct_parts.append(f"Structure: {ex['structure']}")
    legs = ex.get("legs", [])
    if legs:
        leg_strs = [f"{l.get('action','')} {l.get('type','')} {l.get('strike','')} {l.get('exp','')}" for l in legs]
        struct_parts.append(f"Legs: {' / '.join(leg_strs)}")
    if struct_parts:
        card_lines.append(" | ".join(struct_parts))

    # Line 3: Entry / Exit
    lvl = []
    if ex.get("entry_trigger"):
        lvl.append(f"Entry: {ex['entry_trigger']}")
    if ex.get("stop_loss"):
        lvl.append(f"Stop: {ex['stop_loss']}")
    if ex.get("profit_target"):
        lvl.append(f"Target: {ex['profit_target']}")
    if ex.get("time_stop"):
        lvl.append(f"DTE: {ex['time_stop']}")
    if lvl:
        card_lines.append(" | ".join(lvl))

    # Line 4: Risk
    risk = []
    if ex.get("max_loss"):
        risk.append(f"Max Loss: {ex['max_loss']}")
    if ex.get("max_profit"):
        risk.append(f"Max Profit: {ex['max_profit']}")
    if ex.get("allocation"):
        risk.append(f"Alloc: {ex['allocation']}")
    if risk:
        card_lines.append(" | ".join(risk))

    # Line 5: Thesis
    if ex.get("thesis"):
        card_lines.append(f"Thesis: {ex['thesis']}")

    return "\n".join(card_lines)


class OptionsStrategistRole(AIRole):
    """
    Options Strategist Role — P3: per-symbol execution plans.

    Tier 3 architecture:
      - gate_audit_batch() → P3a: gate verdicts (JSON)
      - analyze_batch() → P3b: execution plans for approved symbols (JSON)
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
        self._gate_audit_cache: Optional[str] = None
        self._exec_plan_cache: Optional[str] = None
        
        # Enable progress logging on the LLM provider
        AIRole.enable_llm_progress_logging(
            llm,
            role_name="OptionsStrategist",
            identity=identity.identity_key,
            phase="P3",
        )

    @property
    def role_type(self) -> RoleType:
        return RoleType.ANALYSIS

    def _compose_gate_audit_prompt(self) -> str:
        """P3a: Identity + gate audit instructions."""
        if self._gate_audit_cache is None:
            identity_prompt = self.identity.get_system_prompt()
            self._gate_audit_cache = f"{identity_prompt}\n\n---\n\n{GATE_AUDIT_SYSTEM}"
        return self._gate_audit_cache

    def _compose_exec_plan_prompt(self) -> str:
        """P3b: Identity + execution plan instructions."""
        if self._exec_plan_cache is None:
            identity_prompt = self.identity.get_system_prompt()
            self._exec_plan_cache = f"{identity_prompt}\n\n---\n\n{EXEC_PLAN_SYSTEM}"
        return self._exec_plan_cache

    async def gate_audit_batch(
        self,
        symbol_data_json: str,
        global_context: str,
    ) -> RoleOutput:
        """
        P3a: Gate audit for a batch of symbols.

        Returns JSON verdict array in RoleOutput.content.
        """
        system_prompt = self._compose_gate_audit_prompt()
        user_prompt = GATE_AUDIT_USER.format(
            global_context=global_context,
            symbol_data_json=symbol_data_json,
        )

        logger.info(
            f"P3a GateAudit: Batch audit "
            f"(context={len(global_context)} chars, data={len(symbol_data_json)} chars, "
            f"identity={self.identity.identity_key}, model={self.model_id})"
        )
        logger.debug(f"P3a system_prompt length: {len(system_prompt)}")
        logger.debug(f"P3a user_prompt length: {len(user_prompt)}")

        from tradercat.config import settings

        content = await self.llm.generate_thought(
            prompt=user_prompt,
            model_id=self.model_id,
            system_prompt=system_prompt,
            api_key=self.api_key,
            max_tokens=settings.llm_max_tokens_p3a,
        )

        return RoleOutput(
            role=RoleType.ANALYSIS,
            identity=self.identity.identity_key,
            content=content,
            model_used=self.model_id,
            metadata={"analysis_type": "gate_audit"},
        )

    async def analyze_batch(
        self,
        symbol_data_json: str,
        global_context: str,
    ) -> RoleOutput:
        """
        P3b: Execution plans for pre-approved symbols.

        Input symbol_data_json includes verdict from P3a.
        Returns JSON execution plan array in RoleOutput.content.
        """
        system_prompt = self._compose_exec_plan_prompt()
        user_prompt = EXEC_PLAN_USER.format(
            global_context=global_context,
            symbol_data_json=symbol_data_json,
        )

        logger.info(
            f"P3b ExecPlan: Batch analysis "
            f"(context={len(global_context)} chars, data={len(symbol_data_json)} chars, "
            f"identity={self.identity.identity_key}, model={self.model_id})"
        )
        logger.debug(f"P3b system_prompt length: {len(system_prompt)}")
        logger.debug(f"P3b user_prompt length: {len(user_prompt)}")

        from tradercat.config import settings

        content = await self.llm.generate_thought(
            prompt=user_prompt,
            model_id=self.model_id,
            system_prompt=system_prompt,
            api_key=self.api_key,
            max_tokens=settings.llm_max_tokens_p3b,
        )

        return RoleOutput(
            role=RoleType.ANALYSIS,
            identity=self.identity.identity_key,
            content=content,
            model_used=self.model_id,
            metadata={"analysis_type": "execution_plan"},
        )

    async def execute(self, **kwargs) -> RoleOutput:
        return await self.analyze_batch(
            symbol_data_json=kwargs["symbol_data_json"],
            global_context=kwargs.get("global_context", ""),
        )
