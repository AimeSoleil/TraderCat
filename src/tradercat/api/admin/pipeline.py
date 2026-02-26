"""Admin pipeline API endpoints."""
from datetime import date, datetime
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select, update
from pydantic import BaseModel

from tradercat.api.deps import CurrentAdminUser, DatabaseSession
from tradercat.models import PipelineRun, PipelineStatus, LlmToken

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

    - If a pipeline is currently RUNNING for today, the request is rejected.
    - If a previous run exists (COMPLETED / FAILED / PENDING), it will be
      re-run and all output data (signals, reports) will be overwritten via
      upsert.

    Admin-only endpoint.
    """
    from datetime import datetime
    from tradercat.pipeline.orchestrator import PipelineOrchestrator

    target_date = run_date or datetime.utcnow().date()

    # ── Guard: at least one active LLM token must exist ──
    token_result = await db.execute(
        select(LlmToken).where(LlmToken.is_active == True).limit(1)
    )
    if not token_result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No active LLM token configured. "
                   "Add an active token via /api/admin/llm-tokens before triggering the pipeline.",
        )

    # Block if any pipeline is already RUNNING for today
    today = datetime.utcnow().date()
    result = await db.execute(
        select(PipelineRun).where(
            PipelineRun.run_date == today,
            PipelineRun.status == PipelineStatus.RUNNING.value,
        )
    )
    running = result.scalars().first()
    if running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A pipeline is already running today (run_id={running.id}). "
                   "Wait for it to finish before triggering again.",
        )

    # Check if a run already exists for the target date
    result = await db.execute(
        select(PipelineRun).where(PipelineRun.run_date == target_date)
    )
    existing_run = result.scalars().first()

    # Trigger pipeline execution in background (force=True to overwrite)
    orchestrator = PipelineOrchestrator()
    import asyncio
    asyncio.create_task(orchestrator.run_pipeline(target_date, force=True))

    if existing_run:
        return PipelineTriggerResponse(
            message=f"Pipeline re-triggered — previous {existing_run.status} run will be overwritten",
            run_id=str(existing_run.id),
            run_date=existing_run.run_date,
            status="pending",
        )
    return PipelineTriggerResponse(
        message="Pipeline triggered successfully",
        run_id="pending",
        run_date=target_date,
        status="pending",
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
        status=pipeline_run.status,
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


class PipelineCancelResponse(BaseModel):
    """Response for pipeline cancel."""
    message: str
    run_id: str
    run_date: date
    previous_status: str
    new_status: str


@router.post("/cancel", response_model=PipelineCancelResponse)
async def cancel_pipeline(
    db: DatabaseSession,
    admin: CurrentAdminUser,
    run_date: date | None = Query(None, description="Date of the pipeline run to cancel (defaults to today)"),
):
    """
    Force-cancel a stuck pipeline run by setting its status to FAILED.

    Use this when a pipeline was interrupted externally (e.g. container restart,
    OOM kill) and is still marked as RUNNING, which blocks re-triggering.

    Admin-only endpoint.
    """
    target_date = run_date or datetime.utcnow().date()

    result = await db.execute(
        select(PipelineRun).where(
            PipelineRun.run_date == target_date,
            PipelineRun.status == PipelineStatus.RUNNING.value,
        )
    )
    pipeline_run = result.scalars().first()

    if not pipeline_run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No RUNNING pipeline found for {target_date}. "
                   "Only RUNNING pipelines can be cancelled.",
        )

    previous_status = pipeline_run.status
    pipeline_run.status = PipelineStatus.FAILED.value
    pipeline_run.error_log = (
        (pipeline_run.error_log or "")
        + f"\n[admin-cancel] Force-cancelled by admin at {datetime.utcnow().isoformat()}Z"
    ).strip()
    pipeline_run.completed_at = datetime.utcnow()

    await db.commit()

    return PipelineCancelResponse(
        message=f"Pipeline for {target_date} cancelled — you can now re-trigger it.",
        run_id=str(pipeline_run.id),
        run_date=pipeline_run.run_date,
        previous_status=previous_status,
        new_status=PipelineStatus.FAILED.value,
    )
