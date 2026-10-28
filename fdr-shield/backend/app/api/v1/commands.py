"""Natural-language command plan, confirm, cancel, history and progress API."""
from __future__ import annotations
import asyncio
import json
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session, SessionLocal
from app.core.deps import Pagination, get_current_user, is_current_access_session, pagination, get_client_ip, require_roles
from app.core.security import decode_token
from app.core.exceptions import NotFound, PermissionDenied
from app.core.enums import Role
from app.models.workflow import CommandExecution
from app.models.user import User
from app.schemas.workflow import CommandCancelRequest, CommandConfirmRequest, CommandInterpretRequest
from app.services import command_service
from app.services.event_bus import get_event_bus

router = APIRouter()
COMMAND_ACTORS=require_roles(Role.INSTITUTION,Role.AICTE_OFFICIAL,Role.ADMIN)


@router.post('/interpret', status_code=201)
async def interpret_command(
    body: CommandInterpretRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user = Depends(COMMAND_ACTORS)
):
    from app.services.rate_limit_service import enforce_rate_limit
    from app.core.config import get_settings
    await enforce_rate_limit('commands',f'{user.id}:{get_client_ip(request)}',get_settings().rate_limit_commands_per_minute,60)
    command, plan = await command_service.interpret(session,user,body.text,body.idempotency_key,
        body.conversation_id)
    if command is None:
        return {'mode':'chat','reply':plan['reply'],'interpreter':plan['interpreter'],
            'conversation_id':plan.get('conversation_id'),'message_id':plan.get('message_id')}
    from app.services.local_execution_service import run_inline_command_if_enabled
    ran_inline=await run_inline_command_if_enabled(session,command.id)
    if ran_inline: await session.refresh(command)
    
    # Step 9.4 contract: {command_id, plan: [{step, tool, resolved_targets[], effect_summary, requires_confirmation}], warnings[]}
    steps = plan.get('steps') or [{
        'step': 1,
        'tool': plan.get('tool', plan.get('intent')),
        'resolved_targets': plan.get('resolved_targets', []),
        'effect_summary': plan.get('effect_summary', ''),
        'requires_confirmation': plan.get('requires_confirmation', False),
    }]
    
    return {
        'mode': 'action',
        'command_id': command.id,
        'status': command.status,
        'plan': steps,
        'plan_hash': command.plan_hash,
        'requires_confirmation': command.requires_confirmation,
        'queued': command.status in {'confirmed','running'},
        'result_summary':command.result_summary,
        'interpreter':plan.get('interpreter'),
        'warnings': plan.get('warnings', []),
    }


@router.post('/{command_id}/confirm')
async def confirm_command(
    command_id: int,
    body: CommandConfirmRequest,
    session: AsyncSession = Depends(get_session),
    user = Depends(COMMAND_ACTORS)
):
    command = await command_service.confirm(session, user, command_id, body.plan_hash)
    from app.services.local_execution_service import run_inline_command_if_enabled
    ran_inline=await run_inline_command_if_enabled(session,command.id)
    if ran_inline: await session.refresh(command)
    return {'command_id': command.id, 'status': command.status,
        'queued':command.status in {'confirmed','running'},'result_summary':command.result_summary}


@router.post('/{command_id}/cancel')
async def cancel_command(
    command_id: int,
    body: CommandCancelRequest,
    session: AsyncSession = Depends(get_session),
    user = Depends(COMMAND_ACTORS)
):
    command = await command_service.cancel(session, user, command_id, body.reason)
    return {'command_id': command.id, 'status': command.status}


@router.get('')
async def command_history(
    conversation_id: str | None = None,
    page: Pagination = Depends(pagination),
    session: AsyncSession = Depends(get_session),
    user = Depends(COMMAND_ACTORS)
):
    query = select(CommandExecution).order_by(CommandExecution.created_at.desc())
    if conversation_id is not None:
        query=query.where(CommandExecution.user_id==user.id,
            CommandExecution.conversation_id==conversation_id)
    elif user.role != Role.ADMIN.value:
        query = query.where(CommandExecution.user_id == user.id)
    rows = list((await session.scalars(query.offset(page.skip).limit(page.limit))).all())
    return [
        {
            'id': row.id,
            'mode':(row.interpreted_plan or {}).get('mode','action'),
            'conversation_id':row.conversation_id,
            'raw_command': row.raw_command,
            'intent': (row.interpreted_plan or {}).get('intent'),
            'tool': (row.interpreted_plan or {}).get('tool'),
            'status': row.status,
            'requires_confirmation': row.requires_confirmation,
            'result_summary': row.result_summary,
            'assistant_reply':row.result_summary if (row.interpreted_plan or {}).get('mode')=='chat' else None,
            'interpreter':(row.interpreted_plan or {}).get('interpreter'),
            'created_at': row.created_at,
            'updated_at': row.updated_at,
        }
        for row in rows
    ]


@router.get('/{command_id}')
async def command_detail(
    command_id: int,
    session: AsyncSession = Depends(get_session),
    user = Depends(COMMAND_ACTORS)
):
    command = await session.get(CommandExecution, command_id)
    if not command or (user.role != Role.ADMIN.value and command.user_id != user.id):
        raise NotFound('Command not found.')
    return {
        'id': command.id,
        'raw_command': command.raw_command,
        'interpreted_plan': command.interpreted_plan,
        'plan_hash': command.plan_hash,
        'authorization_result': command.authorization_result,
        'requires_confirmation': command.requires_confirmation,
        'status': command.status,
        'steps': command.steps,
        'result_summary': command.result_summary,
        'created_at': command.created_at,
        'updated_at': command.updated_at,
    }


@router.get('/{command_id}/stream')
async def command_stream(
    command_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user = Depends(COMMAND_ACTORS)
):
    command = await session.get(CommandExecution, command_id)
    if not command or (user.role != Role.ADMIN.value and command.user_id != user.id):
        raise NotFound('Command not found.')

    bus = get_event_bus()

    async def stream():
        # Emit initial state snapshot immediately
        snapshot = {
            'status': command.status,
            'steps': command.steps,
            'result_summary': command.result_summary,
            'updated_at': command.updated_at
        }
        yield f'event: command.progress\ndata: {json.dumps(snapshot, default=str)}\n\n'
        if command.status in {'succeeded', 'failed', 'cancelled'}:
            return

        channel = f"command:{command_id}"
        async for event in bus.subscribe(channel):
            if await request.is_disconnected():
                return

            # Verification of user status
            try: live_claims=decode_token(request.cookies.get('access_token',''))
            except Exception: live_claims={}
            async with SessionLocal() as check_session:
                live_user = await check_session.get(User, user.id)
                live_command = await check_session.get(CommandExecution, command_id)
                session_valid=bool(live_user and await is_current_access_session(check_session,live_user,live_claims)
                    and live_user.role in {Role.INSTITUTION.value,Role.AICTE_OFFICIAL.value,Role.ADMIN.value})

            if not session_valid:
                yield 'event: stream.revoked\ndata: {}\n\n'
                return

            if event is None:
                # Heartbeat
                yield ': heartbeat\n\n'
                # Check if terminal status was reached in DB
                if live_command and live_command.status in {'succeeded', 'failed', 'cancelled'}:
                    snap = {
                        'status': live_command.status,
                        'steps': live_command.steps,
                        'result_summary': live_command.result_summary,
                        'updated_at': live_command.updated_at
                    }
                    yield f'event: command.progress\ndata: {json.dumps(snap, default=str)}\n\n'
                    return
                continue

            # Stream event from pub/sub
            yield f'event: {event.event_type}\ndata: {json.dumps(event.payload, default=str)}\n\n'
            if event.payload.get('status') in {'succeeded', 'failed', 'cancelled'}:
                return

    return StreamingResponse(
        stream(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )
