"""Strategy API endpoints."""
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from tradercat.api.deps import CurrentUser, DatabaseSession
from tradercat.models import StrategyConfig
from tradercat.schemas.strategy import (
    StrategyListResponse,
    StrategyWithUserConfig,
    StrategyConfigUpdate,
    StrategyConfigResponse,
    StrategyInfo,
)

# Import strategy preset functions
from tradercat.core.strategy.bbands_breakout_strategy import make_bbands_breakout_presets
from tradercat.core.strategy.bbands_reversal_strategy import make_bbands_reversal_presets
from tradercat.core.strategy.candlestick_reversal_strategy import make_candlestick_reversal_presets
from tradercat.core.strategy.chart_pattern_strategy import make_chart_pattern_presets
from tradercat.core.strategy.divergence_strategy import make_divergence_presets
from tradercat.core.strategy.fibonacci_retracement_strategy import make_fibonacci_presets
from tradercat.core.strategy.momentum_strategy import make_momentum_presets
from tradercat.core.strategy.sector_rotation_strategy import make_sector_rotation_presets

router = APIRouter(prefix="/strategies", tags=["strategies"])


# Strategy metadata mapping
STRATEGY_METADATA = {
    "bbands_breakout": {
        "name": "bbands_breakout",
        "description": "Bollinger Bands Breakout Strategy",
        "default_preset": "gamma",
        "preset_func": make_bbands_breakout_presets,
    },
    "bbands_reversal": {
        "name": "bbands_reversal",
        "description": "Bollinger Bands Reversal Strategy",
        "default_preset": "fade",
        "preset_func": make_bbands_reversal_presets,
    },
    "candlestick_reversal": {
        "name": "candlestick_reversal",
        "description": "Candlestick Reversal Pattern Strategy",
        "default_preset": "gamma_dip",
        "preset_func": make_candlestick_reversal_presets,
    },
    "chart_pattern": {
        "name": "chart_pattern",
        "description": "Chart Pattern Recognition Strategy",
        "default_preset": "momentum_pattern",
        "preset_func": make_chart_pattern_presets,
    },
    "divergence": {
        "name": "divergence",
        "description": "Divergence Detection Strategy",
        "default_preset": "trend_continuation",
        "preset_func": make_divergence_presets,
    },
    "fibonacci_retracement": {
        "name": "fibonacci_retracement",
        "description": "Fibonacci Retracement Strategy",
        "default_preset": "trend_pullback",
        "preset_func": make_fibonacci_presets,
    },
    "momentum": {
        "name": "momentum",
        "description": "Momentum Trend Strategy",
        "default_preset": "swing_momentum",
        "preset_func": make_momentum_presets,
    },
    "sector_rotation": {
        "name": "sector_rotation",
        "description": "Sector Rotation Strategy",
        "default_preset": "swing",
        "preset_func": make_sector_rotation_presets,
    },
}


@router.get("", response_model=StrategyListResponse)
async def list_strategies(
    db: DatabaseSession,
    current_user: CurrentUser
):
    """
    List all available strategies with default parameters and user overrides.
    """
    # Get user's strategy configs
    result = await db.execute(
        select(StrategyConfig).where(StrategyConfig.user_id == current_user.id)
    )
    user_configs = {config.strategy_name: config for config in result.scalars().all()}
    
    # Build response with strategy info and user configs
    strategies = []
    for strategy_key, metadata in STRATEGY_METADATA.items():
        # Get default parameters from preset function
        presets = metadata["preset_func"]()
        default_preset = metadata["default_preset"]
        default_params = presets.get(default_preset, {})
        
        strategy_info = StrategyInfo(
            name=metadata["name"],
            description=metadata["description"],
            default_preset=default_preset,
            default_parameters=default_params,
        )
        
        # Add user config if exists
        user_config = user_configs.get(metadata["name"])
        strategies.append(
            StrategyWithUserConfig(
                **strategy_info.model_dump(),
                user_config=user_config
            )
        )
    
    return StrategyListResponse(strategies=strategies, total=len(strategies))


@router.put("/{strategy_name}", response_model=StrategyConfigResponse)
async def update_strategy_config(
    strategy_name: str,
    config_update: StrategyConfigUpdate,
    db: DatabaseSession,
    current_user: CurrentUser
):
    """
    Update user-level strategy parameter overrides.
    """
    # Validate strategy name
    if strategy_name not in STRATEGY_METADATA:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy '{strategy_name}' not found"
        )
    
    # Check if config exists
    result = await db.execute(
        select(StrategyConfig).where(
            StrategyConfig.user_id == current_user.id,
            StrategyConfig.strategy_name == strategy_name
        )
    )
    config = result.scalars().first()
    
    if config:
        # Update existing config
        update_data = config_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(config, field, value)
    else:
        # Create new config
        config = StrategyConfig(
            user_id=current_user.id,
            strategy_name=strategy_name,
            preset_name=config_update.preset_name,
            parameters=config_update.parameters,
            is_active=config_update.is_active if config_update.is_active is not None else True,
        )
        db.add(config)
    
    await db.commit()
    await db.refresh(config)
    
    return config
