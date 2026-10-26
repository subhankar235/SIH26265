"""Aggregations for dashboards."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select,func,case,and_
from datetime import timedelta
from app.models.fdr import FDR
from app.models.discrepancy import Discrepancy
from app.schemas.dashboard import DashboardOut,MetricCards,ChartPoint
from app.core.clock import business_today


def _dashboard_redis_client():
    from redis import Redis
    from app.core.config import get_settings
    return Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_connect_timeout=0.25,
        socket_timeout=0.25,
        retry_on_timeout=False,
    )


async def _cache_get(key: str):
    import asyncio
    client = _dashboard_redis_client()
    try:
        return await asyncio.to_thread(client.get, key)
    finally:
        await asyncio.to_thread(client.close)


async def _cache_setex(key: str, ttl: int, value: str) -> None:
    import asyncio
    client = _dashboard_redis_client()
    try:
        await asyncio.to_thread(client.setex, key, ttl, value)
    finally:
        await asyncio.to_thread(client.close)


async def bureau_metrics(session: AsyncSession) -> DashboardOut:
    # SUM active value, count expiring<=30d, pending verifications, open discrepancies; group by bank, month, status; Redis cache 60s
    return await _metrics(session,None)


async def institution_metrics(session: AsyncSession, institution_id: int) -> DashboardOut:
    # Same but scoped + countdown list
    return await _metrics(session,institution_id)

async def _metrics(session,institution_id):
    key=f'fdr-dashboard:v2:{institution_id or "bureau"}'
    try:
        cached=await _cache_get(key)
        if cached:return DashboardOut.model_validate_json(cached)
    except Exception:pass
    filters=[FDR.is_synthetic.is_(False)]
    if institution_id:filters.append(FDR.institution_id==institution_id)
    all_scope=[]
    if institution_id:all_scope.append(FDR.institution_id==institution_id)
    today=business_today(); until=today+timedelta(days=30)
    totals=select(
        func.coalesce(func.sum(case((FDR.status.notin_(['released','expired','renewal_requested']),FDR.amount),else_=0)),0).label('active_value'),
        func.coalesce(func.sum(case((and_(FDR.maturity_date>=today,FDR.maturity_date<=until),1),else_=0)),0).label('expiring'),
        func.coalesce(func.sum(case((FDR.ocr_data.is_(None),1),else_=0)),0).label('pending'),
        func.coalesce(func.sum(case((FDR.trust_badge=='mismatch',1),else_=0)),0).label('discrepancies'),
    )
    if filters:totals=totals.where(*filters)
    totals=(await session.execute(totals)).one()
    synthetic_count=await session.scalar(select(func.count(FDR.id)).where(*all_scope,FDR.is_synthetic.is_(True)))
    unclassified_count=await session.scalar(select(func.count(FDR.id)).where(*all_scope,FDR.is_synthetic.is_(None)))
    metrics=MetricCards(total_active_value=float(totals.active_value),expiring_30d=int(totals.expiring),pending_verifications=int(totals.pending),discrepancies_flagged=int(totals.discrepancies),
        synthetic_records=int(synthetic_count or 0),unclassified_records=int(unclassified_count or 0))
    bank_query=select(FDR.bank_name,func.sum(FDR.amount)).group_by(FDR.bank_name)
    status_query=select(FDR.status,func.count(FDR.id)).group_by(FDR.status)
    maturity_query=select(FDR.maturity_date)
    if filters:
        bank_query=bank_query.where(*filters);status_query=status_query.where(*filters);maturity_query=maturity_query.where(*filters)
    banks=(await session.execute(bank_query)).all();statuses=(await session.execute(status_query)).all()
    months={}
    for maturity in (await session.scalars(maturity_query)).all():
        month=maturity.replace(day=1);months[month]=months.get(month,0)+1
    result=DashboardOut(metrics=metrics,value_by_bank=[ChartPoint(label=k,value=float(v)) for k,v in banks],maturity_timeline=[ChartPoint(label=k.strftime('%b %Y'),value=v) for k,v in sorted(months.items())],status_breakdown=[ChartPoint(label=k,value=int(v)) for k,v in statuses])
    try:await _cache_setex(key,60,result.model_dump_json())
    except Exception:pass
    return result
