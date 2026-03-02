"""Dashboard API endpoint — Active Positions from structured P3 data.

Serves the dashboard's main data: structured portfolio positions for the
current user, filtered by date, with links to the original briefing report
and macro regime context.
"""
from datetime import date
from uuid import UUID
from fastapi import APIRouter, Query
from sqlalchemy import select, func, distinct, case, literal

from tradercat.api.deps import CurrentUser, DatabaseSession
from tradercat.models import (
    SymbolExecutionPlan,
    UserBriefing,
    MacroRegimeContext,
    WatchlistItem,
)
from tradercat.schemas.dashboard import DashboardResponse, DashboardPositionItem

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/positions", response_model=DashboardResponse)
async def get_dashboard_positions(
    db: DatabaseSession,
    current_user: CurrentUser,
    run_date: date | None = Query(None, description="Filter by run date (defaults to latest available)"),
):
    """
    Get structured active positions for the dashboard.

    Returns positions from the user's watchlist that have P3 execution plans
    with structured data, plus links to the briefing report and regime context.
    """
    # --- Get user's watchlist symbols ---
    wl_result = await db.execute(
        select(WatchlistItem.symbol).where(WatchlistItem.user_id == current_user.id)
    )
    user_symbols = [row[0] for row in wl_result.all()]

    # --- Get available dates (from execution plans matching user's watchlist, last 60 days) ---
    dates_query = (
        select(distinct(SymbolExecutionPlan.run_date))
        .where(SymbolExecutionPlan.symbol.in_(user_symbols) if user_symbols else False)
        .order_by(SymbolExecutionPlan.run_date.desc())
        .limit(60)
    )
    dates_result = await db.execute(dates_query)
    available_dates = [str(row[0]) for row in dates_result.all()]

    # --- Determine effective date ---
    if run_date:
        effective_date = run_date
    elif available_dates:
        effective_date = date.fromisoformat(available_dates[0])
    else:
        # No data at all
        return DashboardResponse(
            positions=[],
            run_date=None,
            briefing_id=None,
            regime_label=None,
            regime_score=None,
            total_positions=0,
            available_dates=[],
        )

    # --- Get execution plans for user's watchlist on this date ---
    plans_query = (
        select(SymbolExecutionPlan)
        .where(
            SymbolExecutionPlan.run_date == effective_date,
            SymbolExecutionPlan.symbol.in_(user_symbols) if user_symbols else False,
        )
        .order_by(
            # Approved first (buy/sell), then watchlist, then hold, then reject
            case(
                (SymbolExecutionPlan.verdict == "buy", literal(1)),
                (SymbolExecutionPlan.verdict == "sell", literal(2)),
                (SymbolExecutionPlan.verdict == "watchlist", literal(3)),
                (SymbolExecutionPlan.verdict == "hold", literal(4)),
                (SymbolExecutionPlan.verdict == "reject", literal(5)),
                else_=literal(6),
            ).asc(),
            SymbolExecutionPlan.setup_quality.asc(),
            SymbolExecutionPlan.symbol.asc(),
        )
    )
    plans_result = await db.execute(plans_query)
    plans = plans_result.scalars().all()

    # --- Build position items ---
    positions = []
    for idx, plan in enumerate(plans, start=1):
        sj = plan.structured_json or {}
        ex = sj.get("execution") or {}

        positions.append(DashboardPositionItem(
            id=plan.id,
            symbol=plan.symbol,
            run_date=plan.run_date,
            verdict=plan.verdict,
            setup_quality=plan.setup_quality,
            direction=sj.get("direction"),
            setup_type=sj.get("setup_type"),
            confluence=sj.get("confluence"),
            rr_estimate=sj.get("rr_estimate") or ex.get("rr"),
            rejection_reason=sj.get("rejection_reason"),
            structure=ex.get("structure"),
            legs=ex.get("legs"),
            entry_price=ex.get("entry_trigger"),
            stop_loss=ex.get("stop_loss"),
            profit_target=ex.get("profit_target"),
            time_stop=ex.get("time_stop"),
            max_loss=ex.get("max_loss"),
            max_profit=ex.get("max_profit"),
            allocation=ex.get("allocation"),
            breakeven=ex.get("breakeven"),
            thesis=ex.get("thesis") or ex.get("rationale"),
            rank=idx,
            has_structured_data=bool(sj and ex),
        ))

    # --- Get matching briefing ---
    briefing_result = await db.execute(
        select(UserBriefing.id).where(
            UserBriefing.user_id == current_user.id,
            UserBriefing.run_date == effective_date,
        ).limit(1)
    )
    briefing_row = briefing_result.first()
    briefing_id = str(briefing_row[0]) if briefing_row else None

    # --- Get matching regime ---
    regime_result = await db.execute(
        select(
            MacroRegimeContext.regime_label,
            MacroRegimeContext.regime_score,
        ).where(MacroRegimeContext.run_date == effective_date).limit(1)
    )
    regime_row = regime_result.first()
    regime_label = regime_row[0] if regime_row else None
    regime_score = regime_row[1] if regime_row else None

    return DashboardResponse(
        positions=positions,
        run_date=str(effective_date),
        briefing_id=briefing_id,
        regime_label=regime_label,
        regime_score=regime_score,
        total_positions=len(positions),
        available_dates=available_dates,
    )
