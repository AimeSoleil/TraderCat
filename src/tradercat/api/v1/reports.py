"""Report API endpoints."""
from datetime import date
from uuid import UUID
from fastapi import APIRouter, HTTPException, status, Query
from sqlalchemy import select, func

from tradercat.api.deps import CurrentUser, DatabaseSession
from tradercat.models import Report
from tradercat.schemas.report import ReportResponse, ReportDetail, ReportList

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=ReportList)
async def list_reports(
    db: DatabaseSession,
    current_user: CurrentUser,
    run_date: date | None = Query(None, description="Filter by run date"),
    symbol: str | None = Query(None, max_length=20, description="Filter by symbol"),
    report_type: str | None = Query(None, max_length=50, description="Filter by report type"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """
    List reports for the current user with optional filtering.
    Reports are tenant-isolated (user-specific).
    """
    query = select(Report).where(Report.user_id == current_user.id)
    
    # Apply filters
    if run_date:
        query = query.where(Report.run_date == run_date)
    if symbol:
        query = query.where(Report.symbol == symbol.upper())
    if report_type:
        query = query.where(Report.report_type == report_type)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Get reports with pagination, ordered by date desc
    query = query.order_by(Report.run_date.desc(), Report.created_at.desc())
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    reports = result.scalars().all()
    
    return ReportList(reports=reports, total=total)


@router.get("/{report_id}", response_model=ReportDetail)
async def get_report(
    report_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser
):
    """
    Get full report details including input context.
    Tenant-isolated: users can only access their own reports.
    """
    result = await db.execute(
        select(Report).where(
            Report.id == report_id,
            Report.user_id == current_user.id
        )
    )
    report = result.scalars().first()
    
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found"
        )
    
    return report
