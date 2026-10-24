"""Natural-language command plan, confirm, cancel, history and progress API."""
import asyncio,json
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session,SessionLocal
from app.core.deps import Pagination,get_current_user,pagination
from app.core.exceptions import NotFound
from app.core.enums import Role
from app.models.workflow import CommandExecution
from app.schemas.workflow import CommandCancelRequest,CommandConfirmRequest,CommandInterpretRequest
from app.services import command_service

router=APIRouter()


@router.post('/interpret',status_code=201)
async def interpret_command(body: CommandInterpretRequest,session:AsyncSession=Depends(get_session),user=Depends(get_current_user)):
    if user.role not in {Role.AICTE_OFFICIAL.value,Role.ADMIN.value}:
        from app.core.exceptions import PermissionDenied
        raise PermissionDenied('Command Center is for authorized officials and the Admin read-only subset.')
    command,plan=await command_service.interpret(session,user,body.text,body.idempotency_key)
    return {'command_id':command.id,'status':command.status,'plan':plan,
        'plan_hash':command.plan_hash,'requires_confirmation':command.requires_confirmation,
        'queued':not command.requires_confirmation,
        'warnings':plan.get('warnings',[])}


@router.post('/{command_id}/confirm')
async def confirm_command(command_id:int,body:CommandConfirmRequest,session:AsyncSession=Depends(get_session),user=Depends(get_current_user)):
    command=await command_service.confirm(session,user,command_id,body.plan_hash)
    return {'command_id':command.id,'status':command.status,'queued':True}


@router.post('/{command_id}/cancel')
async def cancel_command(command_id:int,body:CommandCancelRequest,session:AsyncSession=Depends(get_session),user=Depends(get_current_user)):
    command=await command_service.cancel(session,user,command_id,body.reason)
    return {'command_id':command.id,'status':command.status}


@router.get('')
async def command_history(page:Pagination=Depends(pagination),session:AsyncSession=Depends(get_session),user=Depends(get_current_user)):
    query=select(CommandExecution).order_by(CommandExecution.created_at.desc())
    if user.role!='admin':query=query.where(CommandExecution.user_id==user.id)
    rows=list((await session.scalars(query.offset(page.skip).limit(page.limit))).all())
    return [{'id':row.id,'raw_command':row.raw_command,'intent':(row.interpreted_plan or {}).get('intent'),
        'status':row.status,'requires_confirmation':row.requires_confirmation,'result_summary':row.result_summary,
        'created_at':row.created_at,'updated_at':row.updated_at} for row in rows]


@router.get('/{command_id}')
async def command_detail(command_id:int,session:AsyncSession=Depends(get_session),user=Depends(get_current_user)):
    command=await session.get(CommandExecution,command_id)
    if not command or (user.role!='admin' and command.user_id!=user.id):raise NotFound('Command not found.')
    return {'id':command.id,'raw_command':command.raw_command,'interpreted_plan':command.interpreted_plan,
        'plan_hash':command.plan_hash,'authorization_result':command.authorization_result,
        'requires_confirmation':command.requires_confirmation,'status':command.status,
        'steps':command.steps,'result_summary':command.result_summary,'created_at':command.created_at,
        'updated_at':command.updated_at}


@router.get('/{command_id}/stream')
async def command_stream(command_id:int,request:Request,session:AsyncSession=Depends(get_session),user=Depends(get_current_user)):
    command=await session.get(CommandExecution,command_id)
    if not command or (user.role!='admin' and command.user_id!=user.id):raise NotFound('Command not found.')
    async def stream():
        last=None
        for _ in range(120):
            if await request.is_disconnected():return
            async with SessionLocal() as poll:
                from app.models.user import User
                live_user=await poll.get(User,user.id)
                item=await poll.get(CommandExecution,command_id)
            if not item:return
            if not live_user or not live_user.is_active or live_user.status!='active' or (live_user.role!='admin' and item.user_id!=live_user.id):
                yield 'event: stream.revoked\ndata: {}\n\n';return
            snapshot={'status':item.status,'steps':item.steps,'result_summary':item.result_summary,'updated_at':item.updated_at}
            key=(item.status,item.updated_at)
            if key!=last:
                yield f'event: command.progress\ndata: {json.dumps(snapshot,default=str)}\n\n';last=key
            if item.status in {'succeeded','failed','cancelled'}:return
            await asyncio.sleep(1)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
