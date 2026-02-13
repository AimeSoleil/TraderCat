"""Refactor strategy tables: drop strategy_configs, create strategies + strategy_presets

Revision ID: 008
Revises: 007
Create Date: 2026-02-13 22:00:00.000000

"""
import json  # noqa: kept for potential future use
from datetime import datetime
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


# ── Seed data: 7 strategies × 18 presets ───────────────────────

SEED_STRATEGIES = [
    {
        "name": "bbands_breakout",
        "description": "Bollinger Bands Breakout Strategy",
        "strategy_class": "BollingerBreakoutStrategy",
        "default_preset_name": "gamma",
        "presets": [
            {
                "name": "gamma",
                "description": "High-gamma options breakout — tight squeeze + volume spike",
                "parameters": {
                    "bb_period": 20, "bb_std": 2.0,
                    "trailing_bw_window": 60, "bw_percentile_threshold": 10.0,
                    "ema_fast": 9, "ema_slow": 21,
                    "atr_period": 14, "adx_period": 14, "rsi_period": 14,
                    "prior_swing_bars": 3,
                    "vol_zscore_window": 20, "vol_zscore_threshold": 2.5,
                    "score_threshold": 0.70,
                    "weights": {"breakout": 0.30, "squeeze": 0.35, "trend": 0.10, "volume": 0.25, "alignment": 0.00},
                    "min_atr_percent": 1.5, "breakout_margin_atr": 0.15,
                },
            },
            {
                "name": "swing",
                "description": "Multi-day swing breakout — wider squeeze window",
                "parameters": {
                    "bb_period": 20, "bb_std": 2.0,
                    "trailing_bw_window": 120, "bw_percentile_threshold": 25.0,
                    "ema_fast": 9, "ema_slow": 21,
                    "atr_period": 14, "adx_period": 14, "rsi_period": 14,
                    "prior_swing_bars": 5,
                    "vol_zscore_window": 20, "vol_zscore_threshold": 1.8,
                    "score_threshold": 0.65,
                    "weights": {"breakout": 0.30, "squeeze": 0.15, "trend": 0.25, "volume": 0.15, "alignment": 0.15},
                    "min_atr_percent": 1.2, "breakout_margin_atr": 0.25,
                },
            },
            {
                "name": "leaps",
                "description": "LEAPS-focused breakout — long-term squeeze + strong trend",
                "parameters": {
                    "bb_period": 50, "bb_std": 2.2,
                    "trailing_bw_window": 200, "bw_percentile_threshold": 30.0,
                    "ema_fast": 20, "ema_slow": 50,
                    "atr_period": 20, "adx_period": 14, "rsi_period": 21,
                    "prior_swing_bars": 10,
                    "vol_zscore_window": 60, "vol_zscore_threshold": 1.2,
                    "score_threshold": 0.75,
                    "weights": {"breakout": 0.20, "squeeze": 0.10, "trend": 0.30, "volume": 0.10, "alignment": 0.30},
                    "min_atr_percent": 1.0,
                },
            },
        ],
    },
    {
        "name": "bbands_reversal",
        "description": "Bollinger Bands Reversal Strategy",
        "strategy_class": "BBandsReversalStrategy",
        "default_preset_name": "fade",
        "presets": [
            {
                "name": "fade",
                "description": "Mean-reversion fade at extended bands — high vol filter",
                "parameters": {
                    "bb_period": 20, "bb_std": 2.5, "touch_atr_multiplier": 0.2,
                    "adx_period": 14, "adx_threshold": 40.0,
                    "max_time_bars": 2,
                    "vol_zscore_window": 20, "vol_zscore_threshold": 3.0,
                    "rsi_period": 14,
                    "score_threshold": 0.75,
                    "weights": {"candle": 0.40, "trend": 0.10, "volume": 0.35, "momentum": 0.15, "bonus": 0.00},
                },
            },
            {
                "name": "bounce",
                "description": "Lower-band bounce in range-bound markets",
                "parameters": {
                    "bb_period": 20, "bb_std": 2.0, "touch_atr_multiplier": 0.5,
                    "adx_period": 14, "adx_threshold": 20.0,
                    "max_time_bars": 3,
                    "vol_zscore_window": 20, "vol_zscore_threshold": 1.2,
                    "score_threshold": 0.65,
                    "weights": {"candle": 0.25, "trend": 0.35, "volume": 0.15, "momentum": 0.25, "bonus": 0.00},
                },
            },
            {
                "name": "scalp",
                "description": "Quick band-touch scalp — loose threshold",
                "parameters": {
                    "bb_period": 20, "bb_std": 2.0, "touch_atr_multiplier": 0.5,
                    "adx_period": 14, "adx_threshold": 15.0,
                    "max_time_bars": 3,
                    "vol_zscore_window": 20, "vol_zscore_threshold": 1.0,
                    "score_threshold": 0.60,
                    "weights": {"candle": 0.30, "trend": 0.40, "volume": 0.10, "momentum": 0.10, "bonus": 0.10},
                },
            },
        ],
    },
    {
        "name": "candlestick_reversal",
        "description": "Candlestick Reversal Pattern Strategy",
        "strategy_class": "CandlestickReversalStrategy",
        "default_preset_name": "gamma_dip",
        "presets": [
            {
                "name": "gamma_dip",
                "description": "Short-term reversal dip-buy on candlestick patterns",
                "parameters": {
                    "ema_fast": 8, "ema_slow": 21,
                    "atr_period": 14, "rsi_period": 14, "adx_period": 14,
                    "macd_params": {"fast": 12, "slow": 26, "signal": 9},
                    "vol_zscore_window": 10, "vol_zscore_threshold": 1.5,
                    "score_threshold": 0.60,
                    "weights": {"candle": 0.40, "trend_dir": 0.15, "volume": 0.20, "momentum": 0.15, "trend_strength": 0.0, "confirm": 0.10},
                },
            },
            {
                "name": "trend_swing",
                "description": "Swing-trade reversal aligned with broader trend",
                "parameters": {
                    "ema_fast": 20, "ema_slow": 50,
                    "atr_period": 14, "rsi_period": 14, "adx_period": 14,
                    "macd_params": {"fast": 12, "slow": 26, "signal": 9},
                    "vol_zscore_window": 20, "vol_zscore_threshold": 1.2,
                    "score_threshold": 0.70,
                    "weights": {"candle": 0.25, "trend_dir": 0.35, "trend_strength": 0.20, "volume": 0.10, "momentum": 0.10, "confirm": 0.00},
                },
            },
            {
                "name": "reversal_climax",
                "description": "Climactic volume reversal on major trend exhaustion",
                "parameters": {
                    "ema_fast": 50, "ema_slow": 200,
                    "atr_period": 14, "rsi_period": 14, "adx_period": 14,
                    "macd_params": {"fast": 12, "slow": 26, "signal": 9},
                    "vol_zscore_window": 50, "vol_zscore_threshold": 2.5,
                    "score_threshold": 0.80,
                    "weights": {"candle": 0.30, "volume": 0.35, "momentum": 0.25, "trend_dir": 0.00, "trend_strength": 0.05, "confirm": 0.05},
                },
            },
        ],
    },
    {
        "name": "chart_pattern",
        "description": "Chart Pattern Recognition Strategy",
        "strategy_class": "ChartPatternStrategy",
        "default_preset_name": "momentum_pattern",
        "presets": [
            {
                "name": "macro_breakout",
                "description": "Long-term chart pattern breakout with trend confirmation",
                "parameters": {
                    "pivot_left_bars": 10, "pivot_right_bars": 10,
                    "price_similarity_threshold": 0.05, "slope_tolerance": 0.05,
                    "require_volume_breakout": True,
                    "score_threshold": 0.75,
                    "ema_trend_period": 200, "atr_period": 14, "adx_period": 14,
                    "volatility_lookback_window": 50,
                    "vol_score_threshold": 2.0, "vol_zscore_window": 60,
                    "weights": {"pattern_quality": 0.25, "volume_confirm": 0.20, "trend_alignment": 0.35, "trend_strength": 0.15, "volatility_ok": 0.05},
                },
            },
            {
                "name": "momentum_pattern",
                "description": "Short-term momentum-driven pattern breakout",
                "parameters": {
                    "pivot_left_bars": 3, "pivot_right_bars": 3,
                    "price_similarity_threshold": 0.02, "slope_tolerance": 0.15,
                    "require_volume_breakout": True,
                    "score_threshold": 0.65,
                    "ema_trend_period": 50, "atr_period": 14, "adx_period": 14,
                    "volatility_lookback_window": 20,
                    "vol_score_threshold": 1.2, "vol_zscore_window": 20,
                    "weights": {"pattern_quality": 0.20, "volume_confirm": 0.30, "trend_alignment": 0.10, "trend_strength": 0.30, "volatility_ok": 0.10},
                },
            },
            {
                "name": "intraday_breakout",
                "description": "Fast intraday pattern breakout — volume-heavy",
                "parameters": {
                    "pivot_left_bars": 2, "pivot_right_bars": 2,
                    "price_similarity_threshold": 0.03, "slope_tolerance": 0.20,
                    "require_volume_breakout": True,
                    "score_threshold": 0.55,
                    "ema_trend_period": 20, "atr_period": 14, "adx_period": 14,
                    "volatility_lookback_window": 10,
                    "vol_score_threshold": 1.8, "vol_zscore_window": 10,
                    "weights": {"pattern_quality": 0.10, "volume_confirm": 0.40, "trend_alignment": 0.05, "trend_strength": 0.35, "volatility_ok": 0.10},
                },
            },
        ],
    },
    {
        "name": "divergence",
        "description": "Divergence Detection Strategy",
        "strategy_class": "DivergenceStrategy",
        "default_preset_name": "trend_continuation",
        "presets": [
            {
                "name": "trend_continuation",
                "description": "Divergence confirming trend continuation",
                "parameters": {
                    "swing_window": 3, "lookback_swings": 40,
                    "rsi_period": 14, "macd_params": {"fast": 12, "slow": 26, "signal": 9},
                    "atr_period": 14, "adx_period": 14, "vol_zscore_window": 20,
                    "score_threshold": 0.65,
                    "weights": {"divergence": 0.30, "trend_context": 0.35, "momentum": 0.15, "volume": 0.20, "confluence": 0.00},
                },
            },
            {
                "name": "reversal_sniper",
                "description": "Divergence signaling major trend reversal",
                "parameters": {
                    "swing_window": 5, "lookback_swings": 60,
                    "rsi_period": 14, "macd_params": {"fast": 12, "slow": 26, "signal": 9},
                    "atr_period": 14, "adx_period": 14, "vol_zscore_window": 20,
                    "score_threshold": 0.75,
                    "weights": {"divergence": 0.40, "trend_context": 0.10, "momentum": 0.25, "volume": 0.10, "confluence": 0.15},
                },
            },
        ],
    },
    {
        "name": "fibonacci_retracement",
        "description": "Fibonacci Retracement Strategy",
        "strategy_class": "FibonacciRetracementStrategy",
        "default_preset_name": "trend_pullback",
        "presets": [
            {
                "name": "trend_pullback",
                "description": "Pullback to 38.2-55% Fibonacci zone in trend",
                "parameters": {
                    "lookback_swings": 40, "swing_window": 5,
                    "fib_zone": [0.382, 0.55],
                    "ema_fast": 13, "ema_slow": 34,
                    "atr_period": 14, "rsi_period": 14,
                    "macd_params": {"fast": 12, "slow": 26, "signal": 9},
                    "adx_period": 14,
                    "vol_zscore_window": 20, "vol_zscore_threshold": 0.8,
                    "score_threshold": 0.65,
                    "weights": {"zone_trigger": 0.30, "trend_match": 0.30, "adx_strength": 0.20, "momentum": 0.15, "volume": 0.05, "confluence": 0.00},
                },
            },
            {
                "name": "golden_zone",
                "description": "Deep pullback to 61.8-78.6% golden Fibonacci zone",
                "parameters": {
                    "lookback_swings": 100, "swing_window": 10,
                    "fib_zone": [0.618, 0.786],
                    "ema_fast": 50, "ema_slow": 200,
                    "atr_period": 14, "rsi_period": 14,
                    "macd_params": {"fast": 12, "slow": 26, "signal": 9},
                    "adx_period": 14,
                    "vol_zscore_window": 50, "vol_zscore_threshold": 1.5,
                    "score_threshold": 0.75,
                    "weights": {"zone_trigger": 0.40, "trend_match": 0.20, "adx_strength": 0.05, "momentum": 0.20, "volume": 0.10, "confluence": 0.05},
                },
            },
        ],
    },
    {
        "name": "momentum",
        "description": "Momentum Trend Strategy",
        "strategy_class": "MomentumTrendStrategy",
        "default_preset_name": "swing_momentum",
        "presets": [
            {
                "name": "swing_momentum",
                "description": "Multi-week swing momentum with volume confirmation",
                "parameters": {
                    "L": 63, "ema_fast": 10, "ema_slow": 30,
                    "ht_ema_fast": 13, "ht_ema_slow": 26,
                    "adx_period": 14, "atr_period": 14,
                    "vol_zscore_window": 20, "vol_zscore_threshold": 1.5,
                    "score_threshold": 0.70,
                    "weights": {"momentum": 0.40, "trend_strength": 0.20, "daily_trend": 0.20, "ht_trend": 0.10, "volume": 0.05, "confluence": 0.05},
                },
            },
            {
                "name": "core_trend",
                "description": "Long-term core trend following — 200-day alignment",
                "parameters": {
                    "L": 126, "ema_fast": 50, "ema_slow": 200,
                    "ht_ema_fast": 21, "ht_ema_slow": 50,
                    "adx_period": 14, "atr_period": 14,
                    "vol_zscore_window": 60, "vol_zscore_threshold": 1.0,
                    "score_threshold": 0.80,
                    "weights": {"momentum": 0.25, "trend_strength": 0.15, "daily_trend": 0.10, "ht_trend": 0.40, "volume": 0.05, "confluence": 0.05},
                },
            },
        ],
    },
]


def upgrade() -> None:
    # ── 1. Drop old table ──
    op.drop_table("strategy_configs")

    # ── 2. Create strategy_presets first (strategies FK references it) ──
    op.create_table(
        "strategy_presets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("strategy_id", "name", name="uq_strategy_preset_name"),
    )
    op.create_index("ix_strategy_preset_strategy_id", "strategy_presets", ["strategy_id"])

    # ── 3. Create strategies table ──
    op.create_table(
        "strategies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("strategy_class", sa.String(200), nullable=False),
        sa.Column("default_preset_name", sa.String(100), nullable=False),
        sa.Column("active_preset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.ForeignKeyConstraint(
            ["active_preset_id"],
            ["strategy_presets.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_strategies_name", "strategies", ["name"])

    # Add FK from strategy_presets → strategies (after both tables exist)
    op.create_foreign_key(
        "fk_strategy_presets_strategy_id",
        "strategy_presets", "strategies",
        ["strategy_id"], ["id"],
        ondelete="CASCADE",
    )

    # ── 4. Seed data ──
    strategies_tbl = sa.table(
        "strategies",
        sa.column("id", postgresql.UUID),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("strategy_class", sa.String),
        sa.column("default_preset_name", sa.String),
        sa.column("active_preset_id", postgresql.UUID),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    presets_tbl = sa.table(
        "strategy_presets",
        sa.column("id", postgresql.UUID),
        sa.column("strategy_id", postgresql.UUID),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("parameters", postgresql.JSONB),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )

    now = datetime.utcnow()

    for strat_data in SEED_STRATEGIES:
        strategy_id = uuid4()

        # Step 1: Insert strategy (active_preset_id=None initially)
        op.execute(
            strategies_tbl.insert().values(
                id=strategy_id,
                name=strat_data["name"],
                description=strat_data["description"],
                strategy_class=strat_data["strategy_class"],
                default_preset_name=strat_data["default_preset_name"],
                active_preset_id=None,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )

        # Step 2: Insert presets, track the default
        default_preset_id = None
        for preset in strat_data["presets"]:
            preset_id = uuid4()
            if preset["name"] == strat_data["default_preset_name"]:
                default_preset_id = preset_id

            op.execute(
                presets_tbl.insert().values(
                    id=preset_id,
                    strategy_id=strategy_id,
                    name=preset["name"],
                    description=preset["description"],
                    parameters=preset["parameters"],
                    created_at=now,
                    updated_at=now,
                )
            )

        # Step 3: Set active_preset_id to the default preset
        if default_preset_id:
            op.execute(
                strategies_tbl.update()
                .where(strategies_tbl.c.id == strategy_id)
                .values(active_preset_id=default_preset_id)
            )

    print(f"✅  Seeded {len(SEED_STRATEGIES)} strategies with {sum(len(s['presets']) for s in SEED_STRATEGIES)} presets")


def downgrade() -> None:
    # Drop new tables
    op.drop_constraint("fk_strategy_presets_strategy_id", "strategy_presets", type_="foreignkey")
    op.drop_table("strategies")
    op.drop_table("strategy_presets")

    # Recreate old table
    op.create_table(
        "strategy_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_name", sa.String(100), nullable=False),
        sa.Column("preset_name", sa.String(100), nullable=True),
        sa.Column("parameters", postgresql.JSONB(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("user_id", "strategy_name", name="uq_user_strategy"),
    )
    op.create_index("ix_strategy_configs_user_id", "strategy_configs", ["user_id"])
