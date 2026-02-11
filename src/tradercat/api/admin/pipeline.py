"""Admin pipeline API endpoints."""
from datetime import date
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from pydantic import BaseModel

from tradercat.api.deps import CurrentAdminUser, DatabaseSession
from tradercat.models import PipelineRun, PipelineStatus

router = APIRouter(prefix="/pipeline", tags=["admin-pipeline"])


class PipelineRunResponse(BaseModel):
    """Schema for pipeline run response."""
    id: str
    run_date: date
    status: str
    step: str | None
    total_symbols: int
    processed_symbols: int
    total_reports: int
    processed_reports: int
    error_log: str | None
    started_at: str | None
    completed_at: str | None
    created_at: str
    
    model_config = {"from_attributes": True}


class PipelineTriggerResponse(BaseModel):
    """Response for pipeline trigger."""
    message: str
    run_id: str
    run_date: date
    status: str


@router.post("/trigger", response_model=PipelineTriggerResponse)
async def trigger_pipeline(
    db: DatabaseSession,
    admin: CurrentAdminUser,
    run_date: date | None = None
):
    """
    Manually trigger the pipeline for a specific date (or today if not specified).
    Idempotent: will not re-run if already completed for that date.
    Admin-only endpoint.
    """
    from datetime import datetime
    from tradercat.pipeline.orchestrator import PipelineOrchestrator
    
    target_date = run_date or datetime.utcnow().date()
    
    # Check if pipeline run already exists
    result = await db.execute(
        select(PipelineRun).where(PipelineRun.run_date == target_date)
    )
    existing_run = result.scalars().first()
    
    if existing_run:
        if existing_run.status == PipelineStatus.COMPLETED:
            return PipelineTriggerResponse(
                message="Pipeline already completed for this date",
                run_id=str(existing_run.id),
                run_date=existing_run.run_date,
                status=existing_run.status.value
            )
        elif existing_run.status == PipelineStatus.RUNNING:
            return PipelineTriggerResponse(
                message="Pipeline is already running for this date",
                run_id=str(existing_run.id),
                run_date=existing_run.run_date,
                status=existing_run.status.value
            )
    
    # Trigger pipeline execution in background
    orchestrator = PipelineOrchestrator()
    import asyncio
    asyncio.create_task(orchestrator.run_pipeline(target_date))
    
    # Return immediately
    if existing_run:
        return PipelineTriggerResponse(
            message="Pipeline re-triggered for this date",
            run_id=str(existing_run.id),
            run_date=existing_run.run_date,
            status="pending"
        )
    else:
        return PipelineTriggerResponse(
            message="Pipeline triggered successfully",
            run_id="pending",
            run_date=target_date,
            status="pending"
        )


@router.get("/status", response_model=PipelineRunResponse)
async def get_pipeline_status(
    db: DatabaseSession,
    admin: CurrentAdminUser,
    run_date: date | None = None
):
    """
    Get pipeline run status for a specific date (or latest if not specified).
    Admin-only endpoint.
    """
    if run_date:
        result = await db.execute(
            select(PipelineRun).where(PipelineRun.run_date == run_date)
        )
    else:
        result = await db.execute(
            select(PipelineRun).order_by(PipelineRun.run_date.desc()).limit(1)
        )
    
    pipeline_run = result.scalars().first()
    
    if not pipeline_run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pipeline run found"
        )
    
    return PipelineRunResponse(
        id=str(pipeline_run.id),
        run_date=pipeline_run.run_date,
        status=pipeline_run.status.value,
        step=pipeline_run.step,
        total_symbols=pipeline_run.total_symbols,
        processed_symbols=pipeline_run.processed_symbols,
        total_reports=pipeline_run.total_reports,
        processed_reports=pipeline_run.processed_reports,
        error_log=pipeline_run.error_log,
        started_at=pipeline_run.started_at.isoformat() if pipeline_run.started_at else None,
        completed_at=pipeline_run.completed_at.isoformat() if pipeline_run.completed_at else None,
        created_at=pipeline_run.created_at.isoformat()
    )
