"""Aggregated stats for both portals."""

from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.deps import get_current_user, require_roles
from app.services.dashboard_service import bureau_metrics, institution_metrics

router = APIRouter()


@router.get("/bureau")
async def bureau_dashboard(session=Depends(get_session), user=Depends(require_roles('scrutiny_officer','bureau_chief','admin'))):
    # Metric cards + charts; cache in Redis 60s
    return await bureau_metrics(session)


@router.get("/institution")
async def institution_dashboard(session=Depends(get_session), user=Depends(require_roles('institution'))):
    # Own FDR totals + maturity countdowns
    return await institution_metrics(session,user.institution_id)
