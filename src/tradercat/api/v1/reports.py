"""Report API endpoints — Pipeline v2.

Serves:
  - User briefings (from user_briefings table) — tenant-isolated
  - Macro regime contexts (from macro_regime_contexts) — read-only, all authenticated users
  - Symbol execution plans (from symbol_execution_plans) — read-only, all authenticated users
"""
from datetime import date
from uuid import UUID
from fastapi import APIRouter, HTTPException, status, Query
from sqlalchemy import select, func

from tradercat.api.deps import CurrentUser, DatabaseSession
from tradercat.models import MacroRegimeContext, SymbolExecutionPlan, UserBriefing
from tradercat.schemas.report import (
    MacroRegimeContextResponse,
    MacroRegimeContextDetail,
    MacroRegimeContextList,
    SymbolExecutionPlanResponse,
    SymbolExecutionPlanDetail,
    SymbolExecutionPlanList,
    UserBriefingResponse,
    UserBriefingDetail,
    UserBriefingList,
)

router = APIRouter(prefix="/reports", tags=["reports"])


# --- User Briefings ---

@router.get("", response_model=UserBriefingList)
async def list_user_briefings(
    db: DatabaseSession,
    current_user: CurrentUser,
    run_date: date | None = Query(None, description="Filter by run date"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    List personalized briefings for the current user.
    Tenant-isolated: users can only see their own briefings.
    """
    query = select(UserBriefing).where(UserBriefing.user_id == current_user.id)

    if run_date:
        query = query.where(UserBriefing.run_date == run_date)

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(UserBriefing.run_date.desc(), UserBriefing.created_at.desc())
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    reports = result.scalars().all()

    return UserBriefingList(reports=reports, total=total)


# --- Macro Regime Contexts (read-only) ---
# NOTE: /macro routes MUST be defined before /{report_id} to avoid path conflicts

@router.get("/macro", response_model=MacroRegimeContextList)
async def list_macro_regime_contexts(
    db: DatabaseSession,
    current_user: CurrentUser,
    run_date: date | None = Query(None, description="Filter by run date"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    List macro regime context reports.
    Available to all authenticated users (read-only).
    """
    query = select(MacroRegimeContext)

    if run_date:
        query = query.where(MacroRegimeContext.run_date == run_date)

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(MacroRegimeContext.run_date.desc(), MacroRegimeContext.created_at.desc())
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    reports = result.scalars().all()

    return MacroRegimeContextList(reports=reports, total=total)


@router.get("/macro/{report_id}", response_model=MacroRegimeContextDetail)
async def get_macro_regime_context(
    report_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser
):
    """Get full macro regime context details."""
    result = await db.execute(
        select(MacroRegimeContext).where(MacroRegimeContext.id == report_id)
    )
    report = result.scalars().first()

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Macro regime context not found"
        )

    return report


# --- Symbol Execution Plans (read-only) ---

@router.get("/plans", response_model=SymbolExecutionPlanList)
async def list_execution_plans(
    db: DatabaseSession,
    current_user: CurrentUser,
    run_date: date | None = Query(None, description="Filter by run date"),
    symbol: str | None = Query(None, max_length=20, description="Filter by symbol"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    List symbol execution plans.
    Available to all authenticated users (read-only).
    """
    query = select(SymbolExecutionPlan)

    if run_date:
        query = query.where(SymbolExecutionPlan.run_date == run_date)
    if symbol:
        query = query.where(SymbolExecutionPlan.symbol == symbol.upper())

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(SymbolExecutionPlan.run_date.desc(), SymbolExecutionPlan.created_at.desc())
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    reports = result.scalars().all()

    return SymbolExecutionPlanList(reports=reports, total=total)


@router.get("/plans/{report_id}", response_model=SymbolExecutionPlanDetail)
async def get_execution_plan(
    report_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser
):
    """Get full execution plan details."""
    result = await db.execute(
        select(SymbolExecutionPlan).where(SymbolExecutionPlan.id == report_id)
    )
    report = result.scalars().first()

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution plan not found"
        )

    return report


# --- User Briefing by ID (must be after /macro and /plans to avoid path conflicts) ---

@router.get("/{report_id}", response_model=UserBriefingDetail)
async def get_user_briefing(
    report_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser
):
    """
    Get full user briefing details.
    Tenant-isolated: users can only access their own briefings.
    """
    result = await db.execute(
        select(UserBriefing).where(
            UserBriefing.id == report_id,
            UserBriefing.user_id == current_user.id
        )
    )
    report = result.scalars().first()

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Briefing not found"
        )

    return report
