"""Report API endpoints.

Serves user-specific reports (from user_reports table) and
read-only access to global reports (from global_reports table).
"""
from datetime import date
from uuid import UUID
from fastapi import APIRouter, HTTPException, status, Query
from sqlalchemy import select, func

from tradercat.api.deps import CurrentUser, DatabaseSession
from tradercat.models import GlobalReport, UserReport
from tradercat.schemas.report import (
    GlobalReportResponse,
    GlobalReportDetail,
    GlobalReportList,
    UserReportResponse,
    UserReportDetail,
    UserReportList,
)

router = APIRouter(prefix="/reports", tags=["reports"])


# --- User Reports ---

@router.get("", response_model=UserReportList)
async def list_user_reports(
    db: DatabaseSession,
    current_user: CurrentUser,
    run_date: date | None = Query(None, description="Filter by run date"),
    report_type: str | None = Query(None, max_length=50, description="Filter by report type"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    List personalized reports for the current user.
    Tenant-isolated: users can only see their own reports.
    """
    query = select(UserReport).where(UserReport.user_id == current_user.id)
    
    if run_date:
        query = query.where(UserReport.run_date == run_date)
    if report_type:
        query = query.where(UserReport.report_type == report_type)
    
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    query = query.order_by(UserReport.run_date.desc(), UserReport.created_at.desc())
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    reports = result.scalars().all()
    
    return UserReportList(reports=reports, total=total)


# --- Global Reports (read-only, available to all authenticated users) ---
# NOTE: /global routes MUST be defined before /{report_id} to avoid path conflicts

@router.get("/global", response_model=GlobalReportList)
async def list_global_reports(
    db: DatabaseSession,
    current_user: CurrentUser,
    run_date: date | None = Query(None, description="Filter by run date"),
    symbol: str | None = Query(None, max_length=20, description="Filter by symbol"),
    report_type: str | None = Query(None, max_length=50, description="Filter by report type"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    List global reports (macro summaries and execution plans).
    Available to all authenticated users (read-only).
    """
    query = select(GlobalReport)
    
    if run_date:
        query = query.where(GlobalReport.run_date == run_date)
    if symbol:
        query = query.where(GlobalReport.symbol == symbol.upper())
    if report_type:
        query = query.where(GlobalReport.report_type == report_type)
    
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    query = query.order_by(GlobalReport.run_date.desc(), GlobalReport.created_at.desc())
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    reports = result.scalars().all()
    
    return GlobalReportList(reports=reports, total=total)


@router.get("/global/{report_id}", response_model=GlobalReportDetail)
async def get_global_report(
    report_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser
):
    """
    Get full global report details including input context.
    Available to all authenticated users.
    """
    result = await db.execute(
        select(GlobalReport).where(GlobalReport.id == report_id)
    )
    report = result.scalars().first()
    
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Global report not found"
        )
    
    return report


# --- User Report by ID (must be after /global to avoid path conflicts) ---

@router.get("/{report_id}", response_model=UserReportDetail)
async def get_user_report(
    report_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser
):
    """
    Get full user report details including input context.
    Tenant-isolated: users can only access their own reports.
    """
    result = await db.execute(
        select(UserReport).where(
            UserReport.id == report_id,
            UserReport.user_id == current_user.id
        )
    )
    report = result.scalars().first()
    
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found"
        )
    
    return report
