"""Periodic verified export of the append-only hash-chained audit trail."""
import asyncio
import json
import logging
from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.services.audit_service import export_audit_chain
from app.workers.celery_app import celery_app, run_async_task

logger=logging.getLogger(__name__)


@celery_app.task(name='app.workers.tasks_audit.export_audit_snapshot')
def export_audit_snapshot() -> dict:
    return run_async_task(_export())


async def _export() -> dict:
    async with SessionLocal() as session:
        snapshot=await export_audit_chain(session)
    if not snapshot['verification']['valid']:
        logger.error('Audit hash-chain verification failed; export withheld',
            extra={'audit_chain_errors':len(snapshot['verification']['errors'])})
        return {'exported':False,'reason':'chain_verification_failed'}
    from app.integrations import storage_client
    suffix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    key=f"audit_exports/{suffix}-{snapshot['verification']['head_hash'][:16]}.json"
    content=json.dumps(snapshot,sort_keys=True,separators=(',',':'),default=str).encode()
    await asyncio.to_thread(storage_client.put,key,content,'application/json')
    return {'exported':True,'key':key,'records':snapshot['verification']['record_count'],
        'head_hash':snapshot['verification']['head_hash']}
