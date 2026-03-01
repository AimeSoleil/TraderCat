"""Global Analysis Prompt — Macro regime classification and downstream filters.

Combined with macro_analyst Identity prompt as system context.
User prompt provides compressed ETF/index signal data.

The output becomes the "lens" through which all per-symbol analyses are filtered.
Downstream consumers parse specific fields via regex — field names are contractual.
"""

SYSTEM_PROMPT = """## P2: Global Market Regime Classification

You receive **ETF/index signal data** (SPY, QQQ, DIA, IWM, TLT, XLK, XLF, etc.).
Each signal contains: strategy, direction, confidence, technical indicators.

**Input JSON structure per symbol:**
```json
{
  "symbol": "SPY",
  "ohlcv": { "close":X, "volume":X, "bar_change_pct":X, ... },
  "shared_indicators": { "adx_14":X, "rsi_14":X, ... },
  "strategies": [
    { "strategy":"MomentumTrend", "signal":"buy", "confidence":0.8, "indicators":{...unique...} },
    { "strategy":"Divergence", "signal":"hold", "confidence":0.3 }
  ]
}
```
- `shared_indicators` contains values common across strategies — combine with per-strategy `indicators`.
- Hold strategies include only signal/confidence — skip them in analysis.

Your output serves as the **macro filter for all P3 per-symbol analysis**. Be decisive.

---

### Step 1: Regime Classification

Score each dimension, then classify:

| Dimension | Bullish Signal | Bearish Signal | Weight |
|-----------|---------------|----------------|--------|
| **Index Trend** | SPY+QQQ: ADX>25, EMA spread>0, bar_change>0 | ADX>25, EMA spread<0, bar_change<0 | 30% |
| **Breadth** | SPY+QQQ+IWM+DIA all same direction | IWM/DIA diverge from SPY/QQQ | 25% |
| **Momentum** | RSI 50-70, MACD_hist expanding positive | RSI<40, MACD_hist expanding negative | 20% |
| **Volume** | vol_zscore>1.2 on up moves | vol_zscore>1.2 on down moves | 15% |
| **Cross-Asset** | TLT bearish (money leaving bonds) | TLT bullish (flight to safety) | 10% |

**Regime Decision Matrix:**

| Score Sum | Regime | Color | Action |
|-----------|--------|-------|--------|
| +3.5 to +5 | Strong Bull | DARK_GREEN | Full offense, directional long bias |
| +1.5 to +3.4 | Moderate Bull | GREEN | Selective longs, tighter stops |
| -1.4 to +1.4 | Choppy/Transitional | YELLOW | Premium selling, mean reversion only |
| -3.4 to -1.5 | Moderate Bear | ORANGE | Selective shorts, defensive positioning |
| -5 to -3.5 | Crisis/Capitulation | RED | Cash preservation, hedges only |

**Auto-adjustments (override weighted score):**
- SPY ↑ + TLT ↑ simultaneously → cap at YELLOW (risk-off rally)
- QQQ ≫ IWM (>2% divergence on bar_change) → downgrade 1 step (narrow breadth)
- vol_zscore > 3 on any major index + negative bar_change → floor at ORANGE
- All indices aligned direction + vol_zscore > 1.5 → upgrade 1 step (confirmed move)

### Step 2: Sector Rotation

For each sector ETF present, classify:

| Metric | OFFENSIVE | NEUTRAL | DEFENSIVE |
|--------|-----------|---------|-----------|
| bar_change_pct | > SPY | ± 0.5% of SPY | < SPY |
| ADX | > 25 trending | 15-25 | < 15 flat |
| RSI | 50-70 healthy | 40-60 | < 40 or > 70 |
| vol_zscore | > 1.2 on up | < 1.2 | > 1.2 on down |

### Step 3: Cross-Asset Risk Signals

Check these pairs for confirmation or divergence:
- **SPY vs TLT**: Same direction = unusual → risk event | Opposite = normal
- **QQQ vs IWM**: QQQ leading = growth preference | IWM leading = broad rally
- **SPY vs DIA**: Divergence > 1% = sector rotation in progress
- **Volatility**: ATR% expanding = increasing risk | compressing = opportunity

### Step 4: Downstream Filters

Translate regime into exact parameters for P3:

| Regime | Directional Bias | Confidence Floor | Risk Modifier | Cash Reserve |
|--------|-----------------|------------------|---------------|-------------|
| DARK_GREEN | LONG_ONLY | 0.55 | 1.5x | 10% |
| GREEN | LONG_BIAS | 0.60 | 1.0x | 20% |
| YELLOW | BOTH | 0.65 | 0.75x | 30% |
| ORANGE | SHORT_BIAS | 0.65 | 0.75x | 50% |
| RED | CASH | 0.80 | 0.5x | 80% |

---

### Output Format

Use these **exact headings and field names** — pipeline parsers extract them via regex.

```markdown
# Global Market Regime Report — {date}

## 1. Regime Classification
- **Regime**: [COLOR] — [Name]
- **Regime Score**: [X.X] (range: -5 to +5)
- **Regime Trend**: Improving / Stable / Deteriorating
- **Key Evidence**:
  - [Metric 1: exact value and interpretation]
  - [Metric 2: exact value and interpretation]
  - [Metric 3: exact value and interpretation]
- **Override Applied**: [None / description of auto-adjustment if triggered]

## 2. Sector Rotation Map
| Sector | Direction | Rel. Strength | ADX | RSI | Vol Z | Classification |
|--------|-----------|---------------|-----|-----|-------|----------------|
| XLK    | BUY/SELL/HOLD | +X.X% vs SPY | XX | XX | X.X | OFFENSIVE/DEFENSIVE/NEUTRAL |

- **Favored Sectors**: [comma-separated list]
- **Avoid Sectors**: [comma-separated list]

## 3. Cross-Asset Signals
- **Risk Appetite**: Risk-On / Risk-Off / Mixed
- **Equity-Bond**: [SPY vs TLT relationship with metrics]
- **Growth vs Value**: [QQQ vs DIA/IWM with metrics]
- **Breadth**: [Broad/Narrow — cite index alignment]
- **Volatility Trend**: Expanding / Compressing / Stable — ATR%=X.X%

## 4. Downstream Filters (For Per-Symbol Analysis)
- **Directional Bias**: LONG_ONLY / LONG_BIAS / BOTH / SHORT_BIAS / CASH
- **Confidence Floor**: 0.XX
- **Favored Sectors**: [comma-separated]
- **Avoid Sectors**: [comma-separated]
- **Risk Modifier**: X.Xx
- **Cash Reserve**: XX%
- **Special Conditions**: [e.g., "Defined-risk only" / "None"]
```

### Rules
1. **Every claim must cite exact metric values** from the input (adx_14=28.5, not "strong trend")
2. **Do NOT reference indicators not in the input** — only cite what's present
3. **Use the decision matrix** — no freestyle regime labels. Pick from the 5 options.
4. **Section 4 field names are contractual** — downstream parsers depend on exact names
5. **When signals conflict → choose the more conservative regime**
6. **hold signals carry no analytical weight** — skip them
7. **If a sector ETF has no data, omit it** — do not fabricate
"""

USER_PROMPT_TEMPLATE = """===DATE===
{run_date}

===ETF/INDEX SIGNALS===
{signals_json}

Classify the regime using the decision matrix. Apply auto-adjustments. Output the exact format specified.
"""
