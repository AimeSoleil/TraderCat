"""Dashboard API endpoint — Active Positions from structured P3 data.

Serves the dashboard's main data: structured portfolio positions for the
current user, filtered by date, with links to the original briefing report
and macro regime context.
"""
from datetime import date
from fastapi import APIRouter, Query
from sqlalchemy import select, func, distinct, case, literal, or_

from tradercat.api.deps import CurrentUser, DatabaseSession
from tradercat.models import (
    SymbolExecutionPlan,
    SymbolVerdict,
    UserBriefing,
    MacroRegimeContext,
    WatchlistItem,
    SignalRecord,
    SignalScope,
    PipelineRun,
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

    # --- Get available dates (from verdicts matching user's watchlist, last 60 days) ---
    dates_query = (
        select(distinct(SymbolVerdict.run_date))
        .where(SymbolVerdict.symbol.in_(user_symbols) if user_symbols else False)
        .order_by(SymbolVerdict.run_date.desc())
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
            signal_count=0,
            available_dates=[],
        )

    # --- Get verdicts for user's watchlist on this date ---
    verdicts_query = (
        select(SymbolVerdict)
        .where(
            SymbolVerdict.run_date == effective_date,
            SymbolVerdict.symbol.in_(user_symbols) if user_symbols else False,
        )
        .order_by(
            # Approved first (LONG/SHORT), then NEUTRAL
            case(
                (SymbolVerdict.direction == "LONG", literal(1)),
                (SymbolVerdict.direction == "SHORT", literal(2)),
                (SymbolVerdict.direction == "NEUTRAL", literal(3)),
                else_=literal(4),
            ).asc(),
            case(
                (SymbolVerdict.quality == "A+", literal(1)),
                (SymbolVerdict.quality == "A", literal(2)),
                (SymbolVerdict.quality == "B+", literal(3)),
                (SymbolVerdict.quality == "B", literal(4)),
                (SymbolVerdict.quality == "C", literal(5)),
                (SymbolVerdict.quality == "REJECT", literal(6)),
                else_=literal(7),
            ).asc(),
            SymbolVerdict.symbol.asc(),
        )
    )
    verdicts_result = await db.execute(verdicts_query)
    verdicts = verdicts_result.scalars().all()

    # --- Get matching execution plans ---
    plans_query = (
        select(SymbolExecutionPlan)
        .where(
            SymbolExecutionPlan.run_date == effective_date,
            SymbolExecutionPlan.symbol.in_(user_symbols) if user_symbols else False,
        )
    )
    plans_result = await db.execute(plans_query)
    plans_by_symbol = {p.symbol: p for p in plans_result.scalars().all()}

    # --- Build position items ---
    positions = []
    for idx, v in enumerate(verdicts, start=1):
        plan = plans_by_symbol.get(v.symbol)
        legs_data = plan.legs if plan else None

        # Map direction to verdict string for backward compat
        direction_str = (v.direction or "NEUTRAL").upper()
        verdict_label = {"LONG": "buy", "SHORT": "sell"}.get(direction_str, "hold")
        if (v.quality or "").upper() == "REJECT":
            verdict_label = "reject"

        positions.append(DashboardPositionItem(
            id=v.id,
            symbol=v.symbol,
            run_date=v.run_date,
            verdict=verdict_label,
            setup_quality=v.quality,
            direction=v.direction,
            setup_type=v.setup_type,
            confluence=v.confluence,
            rr_estimate=v.rr_estimate or (plan.rr_ratio if plan else None),
            rejection_reason=v.rejection_reason,
            structure=plan.structure if plan else None,
            legs=legs_data,
            entry_price=plan.entry_trigger if plan else None,
            stop_loss=plan.stop_loss if plan else None,
            profit_target=plan.profit_target if plan else None,
            time_stop=plan.time_stop if plan else None,
            max_loss=plan.max_loss if plan else None,
            max_profit=plan.max_profit if plan else None,
            allocation=plan.allocation if plan else None,
            breakeven=plan.breakeven if plan else None,
            thesis=plan.thesis if plan else None,
            rank=idx,
            has_structured_data=plan is not None,
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

    # --- Signal count (lightweight COUNT query — no row fetch) ---
    signal_count_query = (
        select(func.count())
        .select_from(SignalRecord)
        .where(
            SignalRecord.run_date == effective_date,
            or_(
                SignalRecord.scope == SignalScope.GLOBAL,
                (SignalRecord.scope == SignalScope.USER)
                & (SignalRecord.symbol.in_(user_symbols) if user_symbols else False),
            ),
        )
    )
    signal_count = (await db.execute(signal_count_query)).scalar() or 0

    # --- Pipeline run status for this date ---
    pipeline_result = await db.execute(
        select(
            PipelineRun.status,
            PipelineRun.step,
            PipelineRun.error_log,
        ).where(PipelineRun.run_date == effective_date).limit(1)
    )
    pipeline_row = pipeline_result.first()
    pipeline_status = pipeline_row[0] if pipeline_row else None
    pipeline_step = pipeline_row[1] if pipeline_row else None
    pipeline_error = pipeline_row[2] if pipeline_row else None

    return DashboardResponse(
        positions=positions,
        run_date=str(effective_date),
        briefing_id=briefing_id,
        regime_label=regime_label,
        regime_score=regime_score,
        total_positions=len(positions),
        signal_count=signal_count,
        available_dates=available_dates,
        pipeline_status=pipeline_status,
        pipeline_step=pipeline_step,
        pipeline_error=pipeline_error,
    )
