"""Allowlisted Command Center tools with typed Pydantic args, scope checks,
dry-run preview, and execution logic according to Phase 9 specifications.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import re
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional, Set, Type
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ExecutionState, LifecycleState, Role
from app.core.clock import business_today
from app.core.exceptions import InvalidStateTransition, NotFound, PermissionDenied
from app.models.fdr import FDR
from app.models.institution import Institution
from app.models.notification import Notification
from app.models.user import User
from app.models.workflow import (
    CommandExecution,
    ExceptionItem,
    NotificationDeliveryAttempt,
    WorkflowInstance,
    WorkflowNodeExecution,
)
from app.services.audit_service import record


# ---------------------------------------------------------------------------
# Typed Pydantic Arguments for Allowlisted Tools
# ---------------------------------------------------------------------------

class FindFdrsArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=365)
    bank_name: Optional[str] = None
    min_amount: Optional[float] = None


class ListCasesArgs(BaseModel):
    state: str = Field(default='submitted')


class ExplainCaseStatusArgs(BaseModel):
    fdr_ref: str = Field(min_length=1)


class SummarizeFailedNotificationsArgs(BaseModel):
    days: int = Field(default=7, ge=1, le=90)
    channel: Optional[str] = None


class RecheckDocumentArgs(BaseModel):
    fdr_ref: str | list[str]


class RetryNodeArgs(BaseModel):
    fdr_ref: Optional[str] = None
    node_execution_id: Optional[int] = None


class PauseCaseArgs(BaseModel):
    fdr_ref: str
    reason: str = Field(default='Command Center requested pause', min_length=3)


class ResumeCaseArgs(BaseModel):
    fdr_ref: str
    reason: str = Field(default='Command Center requested resume', min_length=3)


class PrepareRemindersArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=180)
    state: str = Field(default='renewal_required')


class EscalateCasesArgs(BaseModel):
    fdr_ref: Optional[str] = None
    filter_state: Optional[str] = None
    reason: str = Field(default='Command Center requested case escalation', min_length=3)


# ---------------------------------------------------------------------------
# Server-side Entity Resolution Helpers
# ---------------------------------------------------------------------------

async def resolve_fdr_reference(session: AsyncSession, actor: User, reference: str) -> FDR:
    """Model-supplied fdr_ref is an untrusted string to look up, never a trusted DB id.
    
    Server resolves via query scoped to the user; ambiguous/none -> error asking user.
    """
    normalized = reference.replace('-', '').replace('_', '').strip().casefold()
    candidates = list((await session.scalars(
        select(FDR).where(FDR.fdr_number.ilike(f'%{reference.strip()}%')).limit(100)
    )).all())
    
    matches = [row for row in candidates if row.fdr_number.replace('-', '').replace('_', '').casefold() == normalized]
    if actor.role == Role.INSTITUTION.value:
        matches = [row for row in matches if row.institution_id == actor.institution_id]
        
    if not matches:
        raise NotFound('No authorized FDR matches that reference.')
    if len(matches) > 1:
        raise InvalidStateTransition('FDR reference is ambiguous; provide a more specific reference.')
    return matches[0]


async def resolve_workflow_for_fdr(session: AsyncSession, fdr_id: int) -> WorkflowInstance:
    workflow = await session.scalar(
        select(WorkflowInstance).where(WorkflowInstance.fdr_id == fdr_id)
        .order_by(WorkflowInstance.execution_version.desc()).limit(1)
    )
    if not workflow:
        raise NotFound('FDR workflow was not found.')
    return workflow


# ---------------------------------------------------------------------------
# Tool Definition & Registry
# ---------------------------------------------------------------------------

@dataclass
class ToolDefinition:
    name: str
    tool_type: Literal['read', 'mutating', 'creates_drafts']
    args_model: Type[BaseModel]
    required_roles: set[str]
    max_batch_size: int
    is_bulk: bool
    confirmation_check: Callable[[dict, list], bool]  # returns True if confirmation is required
    preview: Callable[[AsyncSession, User, BaseModel], Coroutine[Any, Any, dict]]
    execute: Callable[[AsyncSession, User, BaseModel, dict, Optional[Callable]], Coroutine[Any, Any, dict]]


# ---------------------------------------------------------------------------
# Individual Tool Implementations
# ---------------------------------------------------------------------------

# 1. find_fdrs(filter)
async def preview_find_fdrs(session: AsyncSession, actor: User, args: FindFdrsArgs) -> dict:
    today=business_today();upper = today + timedelta(days=args.days)
    query = select(FDR).where(FDR.maturity_date >= today, FDR.maturity_date <= upper).order_by(FDR.maturity_date)
    if actor.role == Role.INSTITUTION.value:
        query = query.where(FDR.institution_id == actor.institution_id)
    if args.bank_name:
        query = query.where(FDR.bank_name.ilike(f"%{args.bank_name}%"))
    if args.min_amount:
        query = query.where(FDR.amount >= args.min_amount)
    
    rows = list((await session.scalars(query.limit(200))).all())
    targets = [{'fdr_id': row.id, 'fdr_number': row.fdr_number, 'maturity_date': row.maturity_date.isoformat(), 'bank_name': row.bank_name, 'amount': float(row.amount)} for row in rows]
    return {
        'targets': targets,
        'snapshot': [],
        'effect_summary': f'Find {len(targets)} FDRs maturing within {args.days} days.',
        'warnings': ['No maturing FDRs found in the specified range.'] if not targets else []
    }


async def execute_find_fdrs(session: AsyncSession, actor: User, args: FindFdrsArgs, plan: dict, progress_cb: Optional[Callable] = None) -> dict:
    return {'found': len(plan.get('resolved_targets', [])), 'results': plan.get('resolved_targets', [])}


# 2. list_cases(state)
async def preview_list_cases(session: AsyncSession, actor: User, args: ListCasesArgs) -> dict:
    query = select(WorkflowInstance, FDR).join(FDR, FDR.id == WorkflowInstance.fdr_id)
    if args.state in {'waiting_human', 'waiting_my_approval'}:
        query = query.where(WorkflowInstance.execution_state == 'waiting_human')
    elif args.state == 'overdue':
        now = datetime.now(timezone.utc)
        query = query.join(ExceptionItem, ExceptionItem.workflow_instance_id == WorkflowInstance.id).where(
            ExceptionItem.status != 'resolved', ExceptionItem.due_at.is_not(None), ExceptionItem.due_at <= now
        )
    else:
        query = query.where(WorkflowInstance.lifecycle_state == args.state)
    
    if actor.role == Role.INSTITUTION.value:
        query = query.where(FDR.institution_id == actor.institution_id)
        
    rows = (await session.execute(query.limit(200))).all()
    targets = [{'workflow_id': wf.id, 'fdr_id': f.id, 'fdr_number': f.fdr_number, 'lifecycle_state': wf.lifecycle_state, 'execution_state': wf.execution_state} for wf, f in rows]
    return {
        'targets': targets,
        'snapshot': [],
        'effect_summary': f'List cases matching state "{args.state}" ({len(targets)} found).',
        'warnings': []
    }


async def execute_list_cases(session: AsyncSession, actor: User, args: ListCasesArgs, plan: dict, progress_cb: Optional[Callable] = None) -> dict:
    return {'count': len(plan.get('resolved_targets', [])), 'cases': plan.get('resolved_targets', [])}


# 3. explain_case_status(fdr)
async def preview_explain_case_status(session: AsyncSession, actor: User, args: ExplainCaseStatusArgs) -> dict:
    fdr = await resolve_fdr_reference(session, actor, args.fdr_ref)
    workflow = await resolve_workflow_for_fdr(session, fdr.id)
    targets = [{'fdr_id': fdr.id, 'fdr_number': fdr.fdr_number, 'workflow_id': workflow.id}]
    return {
        'targets': targets,
        'snapshot': [{'fdr_id': fdr.id, 'workflow_id': workflow.id, 'legacy_status': fdr.status, 'workflow_version': workflow.workflow_version, 'execution_state': workflow.execution_state}],
        'effect_summary': f'Explain case status and diagnostic observations for {fdr.fdr_number}.',
        'warnings': []
    }


async def execute_explain_case_status(session: AsyncSession, actor: User, args: ExplainCaseStatusArgs, plan: dict, progress_cb: Optional[Callable] = None) -> dict:
    fdr = await resolve_fdr_reference(session, actor, args.fdr_ref)
    workflow = await resolve_workflow_for_fdr(session, fdr.id)
    node = await session.scalar(
        select(WorkflowNodeExecution).where(WorkflowNodeExecution.workflow_instance_id == workflow.id)
        .order_by(WorkflowNodeExecution.id.desc()).limit(1)
    )
    return {
        'fdr_number': fdr.fdr_number,
        'lifecycle_state': workflow.lifecycle_state,
        'execution_state': workflow.execution_state,
        'current_node': workflow.current_node,
        'last_error': node.error_message if node else None,
        'last_error_code': node.error_code if node else None,
        'last_node_status': node.status if node else None,
    }


# 4. summarize_failed_notifications(range)
async def preview_summarize_failed_notifications(session: AsyncSession, actor: User, args: SummarizeFailedNotificationsArgs) -> dict:
    lower = datetime.now(timezone.utc) - timedelta(days=args.days)
    query = (
        select(NotificationDeliveryAttempt, Notification, FDR)
        .join(Notification, Notification.id == NotificationDeliveryAttempt.notification_id)
        .join(FDR, FDR.id == Notification.fdr_id)
        .where(NotificationDeliveryAttempt.status.in_(['failed', 'uncertain']), NotificationDeliveryAttempt.scheduled_at >= lower)
    )
    if actor.role == Role.INSTITUTION.value:
        query = query.where(FDR.institution_id == actor.institution_id)
    if args.channel:
        query = query.where(NotificationDeliveryAttempt.provider == args.channel)

    rows = (await session.execute(query.order_by(NotificationDeliveryAttempt.scheduled_at.desc()).limit(200))).all()
    targets = [
        {'fdr_id': f.id, 'fdr_number': f.fdr_number, 'notification_id': n.id, 'channel': a.provider, 'status': a.status, 'error': a.error}
        for a, n, f in rows
    ]
    return {
        'targets': targets,
        'snapshot': [],
        'effect_summary': f'Summarize failed and uncertain notifications over the past {args.days} days ({len(targets)} occurrences).',
        'warnings': []
    }


async def execute_summarize_failed_notifications(session: AsyncSession, actor: User, args: SummarizeFailedNotificationsArgs, plan: dict, progress_cb: Optional[Callable] = None) -> dict:
    targets = plan.get('resolved_targets', [])
    by_channel: dict[str, int] = {}
    for t in targets:
        ch = t.get('channel', 'unknown')
        by_channel[ch] = by_channel.get(ch, 0) + 1
    return {'total_failed': len(targets), 'by_channel': by_channel, 'details': targets[:20]}


# 5. recheck_document(fdr) — mutating (PURE node); yes if >1 case
async def preview_recheck_document(session: AsyncSession, actor: User, args: RecheckDocumentArgs) -> dict:
    refs = [args.fdr_ref] if isinstance(args.fdr_ref, str) else args.fdr_ref
    targets = []
    snapshot = []
    for ref in refs:
        fdr = await resolve_fdr_reference(session, actor, ref)
        workflow = await resolve_workflow_for_fdr(session, fdr.id)
        targets.append({'fdr_id': fdr.id, 'fdr_number': fdr.fdr_number, 'workflow_id': workflow.id})
        snapshot.append({
            'fdr_id': fdr.id, 'workflow_id': workflow.id, 'legacy_status': fdr.status,
            'workflow_version': workflow.workflow_version, 'execution_state': workflow.execution_state
        })
    is_bulk = len(targets) > 1
    return {
        'targets': targets,
        'snapshot': snapshot,
        'effect_summary': f'Start fresh extraction and validation execution for {len(targets)} FDR(s).',
        'warnings': ['Multiple cases targeted: confirmation required before running document recheck.'] if is_bulk else []
    }


async def execute_recheck_document(session: AsyncSession, actor: User, args: RecheckDocumentArgs, plan: dict, progress_cb: Optional[Callable] = None) -> dict:
    from app.services.workflow_state_service import start_new_execution
    results = []
    targets = plan.get('resolved_targets', [])
    for idx, target in enumerate(targets):
        if progress_cb:
            await progress_cb(f"Rechecking document for {target['fdr_number']} ({idx+1}/{len(targets)})", {'step': idx + 1, 'target': target})
        fdr = await session.get(FDR, target['fdr_id'])
        wf = await start_new_execution(session, fdr, actor.id, 'Command Center recheck_document', f"cmd-recheck-{target['fdr_id']}-{datetime.now().timestamp()}")
        results.append({'fdr_number': target['fdr_number'], 'new_workflow_id': wf.id, 'execution_version': wf.execution_version})
    return {'rechecked_count': len(results), 'cases': results}


# 6. retry_node(exec_id) — mutating; yes
async def preview_retry_node(session: AsyncSession, actor: User, args: RetryNodeArgs) -> dict:
    if args.node_execution_id:
        node = await session.get(WorkflowNodeExecution, args.node_execution_id)
        if not node:
            raise NotFound('Node execution not found.')
        workflow = await session.get(WorkflowInstance, node.workflow_instance_id)
        fdr = await session.get(FDR, workflow.fdr_id)
        if actor.role == Role.INSTITUTION.value and fdr.institution_id != actor.institution_id:
            raise NotFound('No authorized FDR matches that reference.')
    elif args.fdr_ref:
        fdr = await resolve_fdr_reference(session, actor, args.fdr_ref)
        workflow = await resolve_workflow_for_fdr(session, fdr.id)
        node = await session.scalar(
            select(WorkflowNodeExecution).where(
                WorkflowNodeExecution.workflow_instance_id == workflow.id,
                WorkflowNodeExecution.status == 'failed'
            ).order_by(WorkflowNodeExecution.id.desc()).limit(1)
        )
        if not node:
            raise NotFound('No failed workflow node exists for that FDR.')
    else:
        raise InvalidStateTransition('Provide an FDR reference or node execution ID to retry.')

    targets = [{'fdr_id': fdr.id, 'fdr_number': fdr.fdr_number, 'workflow_id': workflow.id, 'node_execution_id': node.id, 'node_key': node.node_key}]
    snapshot = [{'fdr_id': fdr.id, 'workflow_id': workflow.id, 'legacy_status': fdr.status, 'workflow_version': workflow.workflow_version, 'execution_state': workflow.execution_state}]
    return {
        'targets': targets,
        'snapshot': snapshot,
        'effect_summary': f'Retry failed node "{node.node_key}" for case {fdr.fdr_number}.',
        'warnings': ['Retrying will re-execute the failed step with stored inputs.']
    }


async def execute_retry_node(session: AsyncSession, actor: User, args: RetryNodeArgs, plan: dict, progress_cb: Optional[Callable] = None) -> dict:
    from app.services.workflow_action_service import retry_failed_node
    target = plan.get('resolved_targets', [])[0]
    wf = await retry_failed_node(
        session, target['workflow_id'], target['node_execution_id'], actor,
        'Command Center retry_node', f"cmd-retry-{target['node_execution_id']}-{datetime.now().timestamp()}", False
    )
    return {'workflow_id': wf.id, 'node_key': target['node_key'], 'execution_state': wf.execution_state}


# 7. pause_case(fdr) & resume_case — mutating; yes
async def preview_pause_case(session: AsyncSession, actor: User, args: PauseCaseArgs) -> dict:
    fdr = await resolve_fdr_reference(session, actor, args.fdr_ref)
    workflow = await resolve_workflow_for_fdr(session, fdr.id)
    if workflow.execution_state in {'paused', 'completed', 'cancelled'}:
        raise InvalidStateTransition(f'Cannot pause a workflow in execution state {workflow.execution_state}.')
    targets = [{'fdr_id': fdr.id, 'fdr_number': fdr.fdr_number, 'workflow_id': workflow.id}]
    snapshot = [{'fdr_id': fdr.id, 'workflow_id': workflow.id, 'legacy_status': fdr.status, 'workflow_version': workflow.workflow_version, 'execution_state': workflow.execution_state}]
    return {
        'targets': targets,
        'snapshot': snapshot,
        'effect_summary': f'Pause workflow execution for {fdr.fdr_number}.',
        'warnings': ['Execution will pause safely at the next idle checkpoint.']
    }


async def execute_pause_case(session: AsyncSession, actor: User, args: PauseCaseArgs, plan: dict, progress_cb: Optional[Callable] = None) -> dict:
    from app.services.workflow_action_service import pause_workflow
    target = plan.get('resolved_targets', [])[0]
    wf = await pause_workflow(session, target['workflow_id'], actor, args.reason, f"cmd-pause-{target['workflow_id']}")
    return {'workflow_id': wf.id, 'execution_state': wf.execution_state}


async def preview_resume_case(session: AsyncSession, actor: User, args: ResumeCaseArgs) -> dict:
    fdr = await resolve_fdr_reference(session, actor, args.fdr_ref)
    workflow = await resolve_workflow_for_fdr(session, fdr.id)
    if workflow.execution_state != 'paused':
        raise InvalidStateTransition(f'Workflow is not paused (current execution state: {workflow.execution_state}).')
    targets = [{'fdr_id': fdr.id, 'fdr_number': fdr.fdr_number, 'workflow_id': workflow.id}]
    snapshot = [{'fdr_id': fdr.id, 'workflow_id': workflow.id, 'legacy_status': fdr.status, 'workflow_version': workflow.workflow_version, 'execution_state': workflow.execution_state}]
    return {
        'targets': targets,
        'snapshot': snapshot,
        'effect_summary': f'Resume paused workflow for {fdr.fdr_number}.',
        'warnings': ['Workflow execution will resume and be requeued in the worker queue.']
    }


async def execute_resume_case(session: AsyncSession, actor: User, args: ResumeCaseArgs, plan: dict, progress_cb: Optional[Callable] = None) -> dict:
    from app.services.workflow_action_service import resume_workflow
    target = plan.get('resolved_targets', [])[0]
    wf = await resume_workflow(session, target['workflow_id'], actor, args.reason, f"cmd-resume-{target['workflow_id']}")
    return {'workflow_id': wf.id, 'execution_state': wf.execution_state}


# 8. prepare_reminders(filter) — creates drafts; yes (sending requires separate confirm)
async def preview_prepare_reminders(session: AsyncSession, actor: User, args: PrepareRemindersArgs) -> dict:
    today=business_today();upper = today + timedelta(days=args.days)
    query = (
        select(FDR, WorkflowInstance)
        .join(WorkflowInstance, WorkflowInstance.fdr_id == FDR.id)
        .where(FDR.maturity_date >= today, FDR.maturity_date <= upper)
    )
    if actor.role == Role.INSTITUTION.value:
        query = query.where(FDR.institution_id == actor.institution_id)
        
    rows = (await session.execute(query.limit(100))).all()
    targets = [{'fdr_id': f.id, 'fdr_number': f.fdr_number, 'maturity_date': f.maturity_date.isoformat(), 'institution_id': f.institution_id} for f, wf in rows]
    return {
        'targets': targets,
        'snapshot': [],
        'effect_summary': f'Prepare reminder DRAFTS for {len(targets)} maturing FDRs. NOTE: Creates drafts only; sending requires separate confirmation.',
        'warnings': ['Draft notifications will be generated. Actual transmission to institutions is gated on separate confirmation.']
    }


async def execute_prepare_reminders(session: AsyncSession, actor: User, args: PrepareRemindersArgs, plan: dict, progress_cb: Optional[Callable] = None) -> dict:
    targets = plan.get('resolved_targets', [])
    created_drafts = []
    for idx, target in enumerate(targets):
        if progress_cb:
            await progress_cb(f"Preparing draft reminder for {target['fdr_number']} ({idx+1}/{len(targets)})", {'step': idx + 1, 'target': target})
        notification = Notification(
            fdr_id=target['fdr_id'],
            institution_id=target['institution_id'],
            type='maturity_reminder',
            channel='email',
            recipient='institution@example.test',
            subject=f"Draft Reminder: FDR {target['fdr_number']} Maturing Soon",
            body=f"Your Fixed Deposit Receipt {target['fdr_number']} matures on {target.get('maturity_date')}.",
            status='draft'
        )
        session.add(notification)
        created_drafts.append({'fdr_number': target['fdr_number'], 'status': 'draft'})
    await session.flush()
    return {'drafts_prepared': len(created_drafts), 'details': created_drafts, 'note': 'Drafts prepared. Sending requires a separate confirmation.'}


# 9. escalate_cases(filter) — mutating; yes (bulk preview mandatory)
async def preview_escalate_cases(session: AsyncSession, actor: User, args: EscalateCasesArgs) -> dict:
    targets = []
    snapshot = []
    if args.fdr_ref:
        fdr = await resolve_fdr_reference(session, actor, args.fdr_ref)
        workflow = await resolve_workflow_for_fdr(session, fdr.id)
        targets.append({'fdr_id': fdr.id, 'fdr_number': fdr.fdr_number, 'workflow_id': workflow.id})
        snapshot.append({'fdr_id': fdr.id, 'workflow_id': workflow.id, 'legacy_status': fdr.status, 'workflow_version': workflow.workflow_version, 'execution_state': workflow.execution_state})
    else:
        # Bulk query for exceptions / overdue cases
        state_filter = args.filter_state or 'correction_required'
        query = select(WorkflowInstance, FDR).join(FDR, FDR.id == WorkflowInstance.fdr_id).where(
            WorkflowInstance.lifecycle_state == state_filter
        )
        if actor.role == Role.INSTITUTION.value:
            query = query.where(FDR.institution_id == actor.institution_id)
        rows = (await session.execute(query.limit(50))).all()
        for wf, f in rows:
            targets.append({'fdr_id': f.id, 'fdr_number': f.fdr_number, 'workflow_id': wf.id})
            snapshot.append({'fdr_id': f.id, 'workflow_id': wf.id, 'legacy_status': f.status, 'workflow_version': wf.workflow_version, 'execution_state': wf.execution_state})
            
    return {
        'targets': targets,
        'snapshot': snapshot,
        'effect_summary': f'Escalate {len(targets)} case(s) to AICTE Bureau Chief/Admin. Bulk preview mandatory.',
        'warnings': ['Bulk escalation marks targeted cases as escalated and creates high-priority exception inbox items.'] if len(targets) > 1 else []
    }


async def execute_escalate_cases(session: AsyncSession, actor: User, args: EscalateCasesArgs, plan: dict, progress_cb: Optional[Callable] = None) -> dict:
    from app.services.workflow_action_service import apply_exception_decision
    targets = plan.get('resolved_targets', [])
    escalated = []
    for idx, target in enumerate(targets):
        if progress_cb:
            await progress_cb(f"Escalating case {target['fdr_number']} ({idx+1}/{len(targets)})", {'step': idx + 1, 'target': target})
        wf = await session.get(WorkflowInstance, target['workflow_id'])
        if wf:
            previous_lifecycle = wf.lifecycle_state
            wf.lifecycle_state = LifecycleState.ESCALATED.value
            exc = await session.scalar(
                select(ExceptionItem).where(
                    ExceptionItem.workflow_instance_id == wf.id,
                    ExceptionItem.status != 'resolved'
                ).limit(1)
            )
            if exc:
                exc.status = 'open'
                exc.priority = 1
                exc.recommended_action = f'Escalated via Command Center: {args.reason}'
            await record(session, actor.id, 'workflow', wf.id, 'COMMAND_CASE_ESCALATED', '',
                         {'lifecycle_state': [previous_lifecycle, LifecycleState.ESCALATED.value]},
                         actor_type='user', institution_id=wf.institution_id)
            escalated.append(target['fdr_number'])
    return {'escalated_count': len(escalated), 'escalated_cases': escalated}


# ---------------------------------------------------------------------------
# Master Tool Registry Map
# ---------------------------------------------------------------------------

TOOLS: Dict[str, ToolDefinition] = {
    'find_fdrs': ToolDefinition(
        name='find_fdrs',
        tool_type='read',
        args_model=FindFdrsArgs,
        required_roles={Role.AICTE_OFFICIAL.value, Role.ADMIN.value, Role.INSTITUTION.value},
        max_batch_size=200,
        is_bulk=False,
        confirmation_check=lambda args, targets: False,
        preview=preview_find_fdrs,
        execute=execute_find_fdrs,
    ),
    'list_cases': ToolDefinition(
        name='list_cases',
        tool_type='read',
        args_model=ListCasesArgs,
        required_roles={Role.AICTE_OFFICIAL.value, Role.ADMIN.value, Role.INSTITUTION.value},
        max_batch_size=200,
        is_bulk=False,
        confirmation_check=lambda args, targets: False,
        preview=preview_list_cases,
        execute=execute_list_cases,
    ),
    'explain_case_status': ToolDefinition(
        name='explain_case_status',
        tool_type='read',
        args_model=ExplainCaseStatusArgs,
        required_roles={Role.AICTE_OFFICIAL.value, Role.ADMIN.value, Role.INSTITUTION.value},
        max_batch_size=1,
        is_bulk=False,
        confirmation_check=lambda args, targets: False,
        preview=preview_explain_case_status,
        execute=execute_explain_case_status,
    ),
    'summarize_failed_notifications': ToolDefinition(
        name='summarize_failed_notifications',
        tool_type='read',
        args_model=SummarizeFailedNotificationsArgs,
        required_roles={Role.AICTE_OFFICIAL.value, Role.ADMIN.value, Role.INSTITUTION.value},
        max_batch_size=200,
        is_bulk=False,
        confirmation_check=lambda args, targets: False,
        preview=preview_summarize_failed_notifications,
        execute=execute_summarize_failed_notifications,
    ),
    'recheck_document': ToolDefinition(
        name='recheck_document',
        tool_type='mutating',
        args_model=RecheckDocumentArgs,
        required_roles={Role.AICTE_OFFICIAL.value},
        max_batch_size=20,
        is_bulk=False,  # dynamically True if len(targets) > 1
        confirmation_check=lambda args, targets: len(targets) > 1,  # "yes if >1 case"
        preview=preview_recheck_document,
        execute=execute_recheck_document,
    ),
    'retry_node': ToolDefinition(
        name='retry_node',
        tool_type='mutating',
        args_model=RetryNodeArgs,
        required_roles={Role.AICTE_OFFICIAL.value},
        max_batch_size=1,
        is_bulk=False,
        confirmation_check=lambda args, targets: True,
        preview=preview_retry_node,
        execute=execute_retry_node,
    ),
    'pause_case': ToolDefinition(
        name='pause_case',
        tool_type='mutating',
        args_model=PauseCaseArgs,
        required_roles={Role.AICTE_OFFICIAL.value},
        max_batch_size=1,
        is_bulk=False,
        confirmation_check=lambda args, targets: True,
        preview=preview_pause_case,
        execute=execute_pause_case,
    ),
    'resume_case': ToolDefinition(
        name='resume_case',
        tool_type='mutating',
        args_model=ResumeCaseArgs,
        required_roles={Role.AICTE_OFFICIAL.value},
        max_batch_size=1,
        is_bulk=False,
        confirmation_check=lambda args, targets: True,
        preview=preview_resume_case,
        execute=execute_resume_case,
    ),
    'prepare_reminders': ToolDefinition(
        name='prepare_reminders',
        tool_type='creates_drafts',
        args_model=PrepareRemindersArgs,
        required_roles={Role.AICTE_OFFICIAL.value},
        max_batch_size=100,
        is_bulk=True,
        confirmation_check=lambda args, targets: True,  # creates drafts, sending requires separate confirm
        preview=preview_prepare_reminders,
        execute=execute_prepare_reminders,
    ),
    'escalate_cases': ToolDefinition(
        name='escalate_cases',
        tool_type='mutating',
        args_model=EscalateCasesArgs,
        required_roles={Role.AICTE_OFFICIAL.value},
        max_batch_size=50,
        is_bulk=True,
        confirmation_check=lambda args, targets: True,  # bulk preview mandatory
        preview=preview_escalate_cases,
        execute=execute_escalate_cases,
    ),
}

# Mapping of Step 9.2 Action Schema intents to canonical tools
INTENT_TO_TOOL = {
    'FIND_MATURING': 'find_fdrs',
    'find_maturing': 'find_fdrs',
    'find_fdrs': 'find_fdrs',
    
    'RECHECK_DOCUMENT': 'recheck_document',
    'recheck_document': 'recheck_document',
    
    'LIST_BY_STATE': 'list_cases',
    'list_by_state': 'list_cases',
    'list_cases': 'list_cases',
    
    'PREPARE_REMINDERS': 'prepare_reminders',
    'prepare_reminders': 'prepare_reminders',
    
    'LIST_OVERDUE': 'list_cases',
    'list_overdue': 'list_cases',
    
    'PAUSE_CASE': 'pause_case',
    'pause_case': 'pause_case',
    
    'RESUME_CASE': 'resume_case',
    'resume_case': 'resume_case',
    
    'RETRY_NODE': 'retry_node',
    'retry_node': 'retry_node',
    
    'LIST_AWAITING_MY_APPROVAL': 'list_cases',
    'list_awaiting_approval': 'list_cases',
    'list_awaiting_my_approval': 'list_cases',
    
    'EXPLAIN_BLOCKED': 'explain_case_status',
    'explain_blocked': 'explain_case_status',
    'explain_case_status': 'explain_case_status',
    
    'SUMMARIZE_FAILED_NOTIFICATIONS': 'summarize_failed_notifications',
    'summarize_failed_notifications': 'summarize_failed_notifications',
    
    'ESCALATE_CASES': 'escalate_cases',
    'escalate_cases': 'escalate_cases',
}
