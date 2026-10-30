"""Allowlisted Command Center tools with typed Pydantic args, scope checks,
dry-run preview, and execution logic according to Phase 9 specifications.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import re
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional, Set, Type
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ExecutionState, LifecycleState, Role
from app.core.clock import business_today
from app.core.exceptions import InvalidStateTransition, NotFound, PermissionDenied
from app.models.fdr import FDR
from app.models.institution import Institution
from app.models.discrepancy import Discrepancy
from app.models.notification import Notification
from app.models.user import User
from app.models.workflow import (
    CommandExecution,
    ExceptionItem,
    NotificationDeliveryAttempt,
    VerificationRun,
    WorkflowInstance,
    WorkflowNodeExecution,
)
from app.services.audit_service import record


# ---------------------------------------------------------------------------
# Typed Pydantic Arguments for Allowlisted Tools
# ---------------------------------------------------------------------------

class StrictCommandArgs(BaseModel):
    model_config=ConfigDict(extra='forbid')


class FindFdrsArgs(StrictCommandArgs):
    days: int = Field(default=30, ge=1, le=365)
    bank_name: Optional[str] = None
    min_amount: Optional[float] = None


class AnalyzeMaturingDiscrepanciesArgs(StrictCommandArgs):
    days: int = Field(default=90,ge=1,le=365)
    limit: int = Field(default=100,ge=1,le=200)


class ListCasesArgs(StrictCommandArgs):
    state: str = Field(default='submitted')


class ExplainCaseStatusArgs(StrictCommandArgs):
    fdr_ref: str = Field(min_length=1)


class GetFdrDetailsArgs(StrictCommandArgs):
    fdr_ref: str = Field(min_length=1)


class GetTaskStatusArgs(StrictCommandArgs):
    command_id: int = Field(ge=1)


class CountFdrsArgs(StrictCommandArgs):
    pass


class ListDiscrepanciesArgs(StrictCommandArgs):
    limit:int=Field(default=100,ge=1,le=200)
    severity:Literal['low','medium','high']|None=None


class ListRecentFdrsArgs(StrictCommandArgs):
    limit: int = Field(default=5, ge=1, le=50)


class SummarizeFailedNotificationsArgs(StrictCommandArgs):
    days: int = Field(default=7, ge=1, le=90)
    channel: Optional[str] = None


class RecheckDocumentArgs(StrictCommandArgs):
    fdr_ref: str | list[str]


class RetryNodeArgs(StrictCommandArgs):
    fdr_ref: Optional[str] = None
    node_execution_id: Optional[int] = None


class PauseCaseArgs(StrictCommandArgs):
    fdr_ref: str
    reason: str = Field(default='Command Center requested pause', min_length=3)


class ResumeCaseArgs(StrictCommandArgs):
    fdr_ref: str
    reason: str = Field(default='Command Center requested resume', min_length=3)


class PrepareRemindersArgs(StrictCommandArgs):
    days: int = Field(default=30, ge=1, le=180)
    state: str = Field(default='renewal_required')


class EscalateCasesArgs(StrictCommandArgs):
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
    query = select(FDR)
    if actor.role == Role.INSTITUTION.value:
        query = query.where(FDR.institution_id == actor.institution_id)
    literal_matches = list((await session.scalars(
        query.where(FDR.fdr_number == reference.strip()).limit(2)
    )).all())
    if len(literal_matches) == 1:
        return literal_matches[0]
    if len(literal_matches) > 1:
        raise InvalidStateTransition(
            'This exact FDR number is duplicated in the database. The record cannot be selected by number alone; '
            'the duplicate records need to be distinguished and corrected.'
        )

    normalized_reference = func.lower(
        func.replace(func.replace(FDR.fdr_number, '-', ''), '_', '')
    )
    matches = list((await session.scalars(
        query.where(normalized_reference == normalized).limit(2)
    )).all())
    if not matches:
        raise NotFound('No authorized FDR matches that reference.')
    if len(matches) > 1:
        raise InvalidStateTransition(
            'This FDR number matches multiple records with different formatting. '
            'Use the exact FDR number as stored in the portal.'
        )
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
    filters = [FDR.maturity_date >= today, FDR.maturity_date <= upper]
    if actor.role == Role.INSTITUTION.value:
        filters.append(FDR.institution_id == actor.institution_id)
    if args.bank_name:
        filters.append(FDR.bank_name.ilike(f"%{args.bank_name}%"))
    if args.min_amount is not None:
        filters.append(FDR.amount >= args.min_amount)
    
    matched_total = await session.scalar(select(func.count(FDR.id)).where(*filters)) or 0
    query = select(FDR).where(*filters).order_by(FDR.maturity_date, FDR.id)
    rows = list((await session.scalars(query.limit(200))).all())
    targets = [{'fdr_id': row.id, 'fdr_number': row.fdr_number, 'maturity_date': row.maturity_date.isoformat(), 'bank_name': row.bank_name, 'amount': float(row.amount)} for row in rows]
    return {
        'targets': targets,
        'snapshot': [],
        'effect_summary': f'Find {matched_total} FDRs maturing within {args.days} days.',
        'warnings': (
            ['No maturing FDRs found in the specified range.'] if not matched_total
            else ['Showing the first 200 matching records; more results are available.']
            if matched_total > len(targets) else []
        ),
        'result_metadata': {
            'matched_total': matched_total,
            'returned_count': len(targets),
            'truncated': matched_total > len(targets),
        },
    }


async def execute_find_fdrs(session: AsyncSession, actor: User, args: FindFdrsArgs, plan: dict, progress_cb: Optional[Callable] = None) -> dict:
    targets = plan.get('resolved_targets', [])
    metadata = plan.get('result_metadata') or {}
    return {
        'found': metadata.get('matched_total', len(targets)),
        'returned_count': len(targets),
        'truncated': metadata.get('truncated', False),
        'results': targets,
    }


async def preview_analyze_maturing_discrepancies(session:AsyncSession,actor:User,
        args:AnalyzeMaturingDiscrepanciesArgs)->dict:
    today=business_today();upper=today+timedelta(days=args.days)
    filters=[FDR.maturity_date>=today,FDR.maturity_date<=upper]
    if actor.role==Role.INSTITUTION.value:filters.append(FDR.institution_id==actor.institution_id)
    total=await session.scalar(select(func.count(FDR.id)).where(*filters)) or 0
    fdr_rows=list((await session.scalars(select(FDR).where(*filters)
        .order_by(FDR.maturity_date,FDR.id).limit(args.limit))).all())
    ids=[row.id for row in fdr_rows]
    discrepancy_rows=[]
    if ids:
        discrepancy_rows=list((await session.scalars(select(Discrepancy).where(
            Discrepancy.fdr_id.in_(ids),Discrepancy.resolved.is_(False),
            Discrepancy.field!='holder').order_by(Discrepancy.fdr_id,Discrepancy.id))).all())
    by_fdr:dict[int,list[dict]]={}
    for row in discrepancy_rows:
        by_fdr.setdefault(row.fdr_id,[]).append({'field':row.field,
            'declared_value':row.declared_value,'observed_value':row.extracted_value,
            'source':row.source,'severity':row.severity})
    targets=[{'fdr_id':row.id,'fdr_number':row.fdr_number,'bank_name':row.bank_name,
        'amount':float(row.amount),'maturity_date':row.maturity_date.isoformat(),
        'lifecycle_state':row.lifecycle_state or row.status,
        'unresolved_discrepancies':by_fdr.get(row.id,[])} for row in fdr_rows]
    return {'targets':targets,'snapshot':[],
        'effect_summary':f'Analyze {len(fdr_rows)} of {total} authorized FDRs maturing within {args.days} days and include stored unresolved discrepancy observations.',
        'warnings':['Result is capped; narrow the date window to retrieve all matching records.'] if total>len(fdr_rows) else [],
        'result_metadata':{'matching_fdrs':total,'returned_fdrs':len(fdr_rows),
            'records_with_discrepancies':sum(bool(by_fdr.get(row.id)) for row in fdr_rows),
            'unresolved_discrepancies':len(discrepancy_rows),'truncated':total>len(fdr_rows)}}


async def execute_analyze_maturing_discrepancies(session:AsyncSession,actor:User,
        args:AnalyzeMaturingDiscrepanciesArgs,plan:dict,progress_cb:Optional[Callable]=None)->dict:
    fresh=await preview_analyze_maturing_discrepancies(session,actor,args)
    return {**fresh['result_metadata'],'days':args.days,'records':fresh['targets'],
        'warnings':fresh['warnings']}


async def _count_authorized_fdrs(session: AsyncSession, actor: User) -> int:
    query = select(func.count(FDR.id))
    if actor.role == Role.INSTITUTION.value:
        query = query.where(FDR.institution_id == actor.institution_id)
    return await session.scalar(query) or 0


async def preview_count_fdrs(session: AsyncSession, actor: User, args: CountFdrsArgs) -> dict:
    total = await _count_authorized_fdrs(session, actor)
    scope = 'your institution' if actor.role == Role.INSTITUTION.value else 'the portal'
    return {
        'targets': [],
        'snapshot': [],
        'effect_summary': f'Count all FDR records visible to this user in {scope}: {total}.',
        'warnings': [],
        'result_metadata': {'total_fdrs': total},
    }


async def execute_count_fdrs(session: AsyncSession, actor: User, args: CountFdrsArgs,
                             plan: dict, progress_cb: Optional[Callable] = None) -> dict:
    return {'total_fdrs': await _count_authorized_fdrs(session, actor)}


async def preview_list_unresolved_discrepancies(session:AsyncSession,actor:User,
        args:ListDiscrepanciesArgs)->dict:
    filters=[Discrepancy.resolved.is_(False),Discrepancy.field!='holder']
    if args.severity:filters.append(Discrepancy.severity==args.severity)
    scope=FDR.institution_id==actor.institution_id if actor.role==Role.INSTITUTION.value else None
    total_query=select(func.count(Discrepancy.id)).join(FDR,FDR.id==Discrepancy.fdr_id).where(*filters)
    rows_query=select(Discrepancy,FDR).join(FDR,FDR.id==Discrepancy.fdr_id).where(*filters)
    if scope is not None:
        total_query=total_query.where(scope);rows_query=rows_query.where(scope)
    total=await session.scalar(total_query) or 0
    rows=list((await session.execute(rows_query.order_by(Discrepancy.id.desc()).limit(args.limit))).all())
    targets=[{'fdr_id':fdr.id,'fdr_number':fdr.fdr_number,'bank_name':fdr.bank_name,
        'lifecycle_state':fdr.lifecycle_state or fdr.status,'field':item.field,
        'declared_value':item.declared_value,'observed_value':item.extracted_value,
        'source':item.source,'severity':item.severity} for item,fdr in rows]
    return {'targets':targets,'snapshot':[],
        'effect_summary':f'Retrieve {len(targets)} of {total} unresolved discrepancy record(s) in your authorized scope.',
        'warnings':['Results are capped; filter by severity to inspect a subset.'] if total>len(targets) else [],
        'result_metadata':{'total':total,'returned':len(targets),'truncated':total>len(targets)}}


async def execute_list_unresolved_discrepancies(session:AsyncSession,actor:User,
        args:ListDiscrepanciesArgs,plan:dict,progress_cb:Optional[Callable]=None)->dict:
    fresh=await preview_list_unresolved_discrepancies(session,actor,args)
    return {**fresh['result_metadata'],'discrepancies':fresh['targets'],'warnings':fresh['warnings']}


async def preview_list_recent_fdrs(session: AsyncSession, actor: User, args: ListRecentFdrsArgs) -> dict:
    query = select(FDR)
    if actor.role == Role.INSTITUTION.value:
        query = query.where(FDR.institution_id == actor.institution_id)
    rows = list((await session.scalars(query.order_by(FDR.id.desc()).limit(args.limit))).all())
    targets = [{
        'fdr_id': row.id,
        'fdr_number': row.fdr_number,
        'bank_name': row.bank_name,
        'amount': float(row.amount),
        'issue_date': row.issue_date.isoformat() if row.issue_date else None,
        'maturity_date': row.maturity_date.isoformat() if row.maturity_date else None,
        'record_status': row.status,
        'lifecycle_state': row.lifecycle_state,
        'execution_state': row.execution_state,
        'verification_level': row.verification_level,
        'trust_badge': row.trust_badge,
        'is_synthetic': row.is_synthetic,
    } for row in rows]
    return {
        'targets': targets,
        'snapshot': [],
        'effect_summary': f'Retrieve the {len(targets)} most recently created authorized FDR record(s).',
        'warnings': [] if targets else ['No FDR records are available in your authorized data scope.'],
        'result_metadata': {'returned_count': len(targets), 'requested_count': args.limit},
    }


async def execute_list_recent_fdrs(session: AsyncSession, actor: User, args: ListRecentFdrsArgs,
                                   plan: dict, progress_cb: Optional[Callable] = None) -> dict:
    records = plan.get('resolved_targets', [])
    return {'count': len(records), 'records': records}


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


async def preview_get_fdr_details(session: AsyncSession, actor: User, args: GetFdrDetailsArgs) -> dict:
    fdr = await resolve_fdr_reference(session, actor, args.fdr_ref)
    return {
        'targets': [{'fdr_id': fdr.id, 'fdr_number': fdr.fdr_number}],
        'snapshot': [],
        'effect_summary': f'Retrieve authorized FDR details and available verification evidence for {fdr.fdr_number}.',
        'warnings': [],
    }


async def execute_get_fdr_details(session: AsyncSession, actor: User, args: GetFdrDetailsArgs,
                                  plan: dict, progress_cb: Optional[Callable] = None) -> dict:
    fdr = await resolve_fdr_reference(session, actor, args.fdr_ref)
    workflow = await session.scalar(
        select(WorkflowInstance)
        .where(WorkflowInstance.fdr_id == fdr.id)
        .order_by(WorkflowInstance.execution_version.desc())
        .limit(1)
    )
    discrepancy_rows = list((await session.scalars(
        select(Discrepancy)
        .where(Discrepancy.fdr_id == fdr.id, Discrepancy.resolved.is_(False))
        .order_by(Discrepancy.id.desc())
        .limit(50)
    )).all())
    verification_rows = list((await session.scalars(
        select(VerificationRun)
        .where(VerificationRun.fdr_id == fdr.id)
        .order_by(VerificationRun.created_at.desc(), VerificationRun.id.desc())
        .limit(5)
    )).all())
    discrepancies = [{
        'field': row.field,
        'declared_value': row.declared_value,
        'observed_value': row.extracted_value,
        'source': row.source,
        'severity': row.severity,
        'resolved': row.resolved,
    } for row in discrepancy_rows if row.field.casefold() != 'holder']
    verifications = [{
        'source': row.source,
        'extraction_engine': row.extraction_engine,
        'verification_level': row.verification_level,
        'confidence': row.confidence,
        'created_at': row.created_at.isoformat() if row.created_at else None,
    } for row in verification_rows]
    extracted=fdr.ocr_data or {}
    expected_ocr_fields=('fdr_number','bank_name','holder_name','amount','issue_date','maturity_date')
    missing_extracted_fields=[field for field in expected_ocr_fields if extracted.get(field) in (None,'')]
    return {
        'fdr': {
            'fdr_number': fdr.fdr_number,
            'bank_name': fdr.bank_name,
            'branch': fdr.branch,
            'amount': float(fdr.amount),
            'issue_date': fdr.issue_date.isoformat() if fdr.issue_date else None,
            'maturity_date': fdr.maturity_date.isoformat() if fdr.maturity_date else None,
            'record_status': fdr.status,
            'trust_badge': fdr.trust_badge,
            'verification_level': fdr.verification_level,
            'is_synthetic': fdr.is_synthetic,
            'missing_extracted_fields':missing_extracted_fields,
            'ocr_confidence':extracted.get('confidence'),
            'document_format':extracted.get('document_format','not_checked'),
        },
        'workflow': {
            'lifecycle_state': workflow.lifecycle_state,
            'execution_state': workflow.execution_state,
            'authorization_state': workflow.authorization_state,
            'current_node': workflow.current_node,
        } if workflow else None,
        'unresolved_discrepancies': discrepancies,
        'verification_runs': verifications,
        'evidence_note': (
            'These are stored portal records and verification observations. They do not prove that an FDR '
            'is genuine or independently verified by a real bank.'
        ),
    }


async def _authorized_command(session:AsyncSession,actor:User,command_id:int)->CommandExecution:
    command=await session.get(CommandExecution,command_id)
    if not command or (actor.role!=Role.ADMIN.value and command.user_id!=actor.id):
        raise NotFound('No authorized task matches that identifier.')
    return command


async def preview_get_task_status(session:AsyncSession,actor:User,args:GetTaskStatusArgs)->dict:
    command=await _authorized_command(session,actor,args.command_id)
    return {'targets':[{'command_id':command.id,'status':command.status}],
        'snapshot':[],'effect_summary':f'Retrieve the current persisted status for authorized task {command.id}.',
        'warnings':[]}


async def execute_get_task_status(session:AsyncSession,actor:User,args:GetTaskStatusArgs,
        plan:dict,progress_cb:Optional[Callable]=None)->dict:
    command=await _authorized_command(session,actor,args.command_id)
    return {'task_id':command.id,'task_type':(command.interpreted_plan or {}).get('tool',
        (command.interpreted_plan or {}).get('mode','command')),'status':command.status,
        'created_at':command.created_at.isoformat() if command.created_at else None,
        'updated_at':command.updated_at.isoformat() if command.updated_at else None,
        'result_summary':command.result_summary,'steps':command.steps or [],
        'requires_confirmation':command.requires_confirmation}


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
    if not refs or len(refs)>20:
        raise InvalidStateTransition('Document recheck supports 1 to 20 explicitly identified FDR references per request.')
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
        select(FDR, WorkflowInstance, Institution)
        .join(WorkflowInstance, WorkflowInstance.fdr_id == FDR.id)
        .join(Institution,Institution.id==FDR.institution_id)
        .where(FDR.maturity_date >= today, FDR.maturity_date <= upper)
    )
    if args.state:query=query.where(WorkflowInstance.lifecycle_state==args.state)
    if actor.role == Role.INSTITUTION.value:
        query = query.where(FDR.institution_id == actor.institution_id)
    rows = (await session.execute(query.order_by(FDR.maturity_date,FDR.id).limit(100))).all()
    targets=[{'fdr_id':f.id,'fdr_number':f.fdr_number,'maturity_date':f.maturity_date.isoformat(),
        'institution_id':f.institution_id,'recipient':institution.contact_email}
        for f,wf,institution in rows]
    missing_contact=sum(not target['recipient'] for target in targets)
    return {
        'targets': targets,
        'snapshot': [],
        'effect_summary': f'Prepare reminder DRAFTS for {len(targets)} maturing FDRs. NOTE: Creates drafts only; sending requires separate confirmation.',
        'warnings': (['Some target institutions have no registered contact email; those draft messages will be omitted.'] if missing_contact else [])+
            ['These are persisted command-result drafts only; no notification is sent.']
    }


async def execute_prepare_reminders(session: AsyncSession, actor: User, args: PrepareRemindersArgs, plan: dict, progress_cb: Optional[Callable] = None) -> dict:
    targets = plan.get('resolved_targets', [])
    drafts=[];omitted=[]
    for idx, target in enumerate(targets):
        if progress_cb:
            await progress_cb(f"Preparing draft reminder for {target['fdr_number']} ({idx+1}/{len(targets)})", {'step': idx + 1, 'target': target})
        if not target.get('recipient'):
            omitted.append({'fdr_number':target['fdr_number'],'reason':'No institution contact email is recorded.'})
            continue
        drafts.append({'fdr_id':target['fdr_id'],'fdr_number':target['fdr_number'],
            'recipient':target['recipient'],'subject':f"Maturity reminder draft: FDR {target['fdr_number']}",
            'body':f"Your Fixed Deposit Receipt {target['fdr_number']} has a recorded maturity date of {target.get('maturity_date')}. Please review its status in the AICTE FDR portal.",
            'status':'draft_not_sent'})
    return {'drafts_prepared':len(drafts),'drafts':drafts,'omitted':omitted,
        'note':'These drafts are part of this persisted Command Center result; no messages were sent.'}


# 9. escalate_cases(filter) — mutating; yes (bulk preview mandatory)
async def preview_escalate_cases(session: AsyncSession, actor: User, args: EscalateCasesArgs) -> dict:
    targets = []
    snapshot = []
    if args.fdr_ref:
        fdr = await resolve_fdr_reference(session, actor, args.fdr_ref)
        workflow = await resolve_workflow_for_fdr(session, fdr.id)
        exception=await session.scalar(select(ExceptionItem).where(
            ExceptionItem.workflow_instance_id==workflow.id,ExceptionItem.status!='resolved')
            .order_by(ExceptionItem.priority,ExceptionItem.id).limit(1))
        if not exception:raise NotFound('No open exception exists for that FDR to escalate.')
        targets.append({'fdr_id':fdr.id,'fdr_number':fdr.fdr_number,'workflow_id':workflow.id,
            'exception_id':exception.id,'reason_code':exception.reason_code})
        snapshot.append({'fdr_id': fdr.id, 'workflow_id': workflow.id, 'legacy_status': fdr.status, 'workflow_version': workflow.workflow_version, 'execution_state': workflow.execution_state})
    else:
        # Escalate only actual open exception records, not every case in a lifecycle state.
        state_filter = args.filter_state or 'correction_required'
        query=select(ExceptionItem,WorkflowInstance,FDR).join(
            WorkflowInstance,WorkflowInstance.id==ExceptionItem.workflow_instance_id).join(
            FDR,FDR.id==WorkflowInstance.fdr_id).where(ExceptionItem.status!='resolved',
                WorkflowInstance.lifecycle_state==state_filter)
        if actor.role == Role.INSTITUTION.value:
            query=query.where(FDR.institution_id==actor.institution_id)
        rows=list((await session.execute(query.order_by(ExceptionItem.priority,ExceptionItem.id).limit(50))).all())
        for exception,wf,f in rows:
            targets.append({'fdr_id':f.id,'fdr_number':f.fdr_number,'workflow_id':wf.id,
                'exception_id':exception.id,'reason_code':exception.reason_code})
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
        await apply_exception_decision(session,actor,target['exception_id'],'escalate',args.reason,
            f"command:{plan.get('_command_id','untracked')}:escalate:{target['exception_id']}")
        escalated.append(target['fdr_number'])
    return {'escalated_count':len(escalated),'escalated_cases':escalated,
        'note':'Escalation was recorded through the exception-decision service.'}


# ---------------------------------------------------------------------------
# Master Tool Registry Map
# ---------------------------------------------------------------------------

TOOLS: Dict[str, ToolDefinition] = {
    'get_task_status':ToolDefinition(name='get_task_status',tool_type='read',
        args_model=GetTaskStatusArgs,
        required_roles={Role.AICTE_OFFICIAL.value,Role.ADMIN.value,Role.INSTITUTION.value},
        max_batch_size=1,is_bulk=False,confirmation_check=lambda args,targets:False,
        preview=preview_get_task_status,execute=execute_get_task_status),
    'analyze_maturing_discrepancies':ToolDefinition(
        name='analyze_maturing_discrepancies',tool_type='read',
        args_model=AnalyzeMaturingDiscrepanciesArgs,
        required_roles={Role.AICTE_OFFICIAL.value,Role.ADMIN.value,Role.INSTITUTION.value},
        max_batch_size=200,is_bulk=False,confirmation_check=lambda args,targets:False,
        preview=preview_analyze_maturing_discrepancies,
        execute=execute_analyze_maturing_discrepancies,
    ),
    'list_recent_fdrs': ToolDefinition(
        name='list_recent_fdrs',
        tool_type='read',
        args_model=ListRecentFdrsArgs,
        required_roles={Role.AICTE_OFFICIAL.value, Role.ADMIN.value, Role.INSTITUTION.value},
        max_batch_size=50,
        is_bulk=False,
        confirmation_check=lambda args, targets: False,
        preview=preview_list_recent_fdrs,
        execute=execute_list_recent_fdrs,
    ),
    'count_fdrs': ToolDefinition(
        name='count_fdrs',
        tool_type='read',
        args_model=CountFdrsArgs,
        required_roles={Role.AICTE_OFFICIAL.value, Role.ADMIN.value, Role.INSTITUTION.value},
        max_batch_size=1,
        is_bulk=False,
        confirmation_check=lambda args, targets: False,
        preview=preview_count_fdrs,
        execute=execute_count_fdrs,
    ),
    'list_unresolved_discrepancies':ToolDefinition(
        name='list_unresolved_discrepancies',tool_type='read',
        args_model=ListDiscrepanciesArgs,
        required_roles={Role.AICTE_OFFICIAL.value,Role.ADMIN.value,Role.INSTITUTION.value},
        max_batch_size=200,is_bulk=False,confirmation_check=lambda args,targets:False,
        preview=preview_list_unresolved_discrepancies,
        execute=execute_list_unresolved_discrepancies),
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
    'get_fdr_details': ToolDefinition(
        name='get_fdr_details',
        tool_type='read',
        args_model=GetFdrDetailsArgs,
        required_roles={Role.AICTE_OFFICIAL.value, Role.ADMIN.value, Role.INSTITUTION.value},
        max_batch_size=1,
        is_bulk=False,
        confirmation_check=lambda args, targets: False,
        preview=preview_get_fdr_details,
        execute=execute_get_fdr_details,
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
    'LIST_UNRESOLVED_DISCREPANCIES':'list_unresolved_discrepancies',
    'list_unresolved_discrepancies':'list_unresolved_discrepancies',
    'GET_TASK_STATUS':'get_task_status','get_task_status':'get_task_status',
    'ANALYZE_MATURING_DISCREPANCIES':'analyze_maturing_discrepancies',
    'analyze_maturing_discrepancies':'analyze_maturing_discrepancies',
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
    'GET_FDR_DETAILS': 'get_fdr_details',
    'get_fdr_details': 'get_fdr_details',
    'COUNT_FDRS': 'count_fdrs',
    'count_fdrs': 'count_fdrs',
    'LIST_RECENT_FDRS': 'list_recent_fdrs',
    'list_recent_fdrs': 'list_recent_fdrs',
    
    'SUMMARIZE_FAILED_NOTIFICATIONS': 'summarize_failed_notifications',
    'summarize_failed_notifications': 'summarize_failed_notifications',
    
    'ESCALATE_CASES': 'escalate_cases',
    'escalate_cases': 'escalate_cases',
}
