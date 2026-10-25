"""Phase 10 — Institution Assistance Agent (Agent A) Service.

Provides:
- 10.1: Context built server-side from caller's own cases only (institution isolation).
- 10.2: Read-mostly, institution-scoped tools:
       get_case_state, list_required_actions, explain_discrepancy, get_deadlines,
       get_renewal_requirements, get_release_requirements.
- 10.4: Deterministic mapping table for "next action" derived from lifecycle_state.
- 10.5: Guardrails: no authenticity claims ("this FDR is genuine"), no invented values
       ("not found in document" when missing).
- 10.6: DAGMM anomaly surfaces only as "unusual pattern — review suggested", never rejection.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
import json
import re
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import LifecycleState, Role
from app.core.exceptions import NotFound, PermissionDenied
from app.models.discrepancy import Discrepancy
from app.models.fdr import FDR
from app.models.workflow import CorrectionRequest, VerificationRun, WorkflowInstance, WorkflowNodeExecution
from app.core.clock import business_today
from app.services.llm_service import generate_grounded_reply


# ---------------------------------------------------------------------------
# Step 10.4: Deterministic Lifecycle Next-Action Mapping Table
# ---------------------------------------------------------------------------

LIFECYCLE_NEXT_ACTIONS: Dict[str, str] = {
    'submitted': 'Wait for AICTE verification; extraction and automated checks are running.',
    'extraction_pending': 'Wait for AICTE verification; document extraction is pending.',
    'extracting': 'Wait for AICTE verification; document extraction is in progress.',
    'validation_pending': 'Automated validation in progress; check back shortly.',
    'validation_failed': 'Upload a corrected FDR document addressing flagged discrepancies.',
    'correction_required': 'Upload a corrected FDR document addressing flagged discrepancies.',
    'awaiting_institution': 'Submit requested corrections or clarification documents to AICTE.',
    'ready_for_scrutiny': 'Under review by AICTE Official. No institution action needed at this time.',
    'under_review': 'Under review by AICTE Official. No institution action needed at this time.',
    'awaiting_official_decision': 'Under review by AICTE Official. No institution action needed at this time.',
    'accepted': 'FDR verified and active in AICTE trust matrix. Monitor maturity date.',
    'renewal_required': 'Submit renewal request with replacement FDR scan before maturity.',
    'renewed': 'FDR successfully renewed. Retain new deposit receipt for records.',
    'release_requested': 'Release request under review by AICTE.',
    'awaiting_release_decision': 'Release request under review by AICTE.',
    'release_approved': 'FDR release approved. Follow instructions for bank encashment.',
    'release_rejected': 'Release request rejected. Review rejection reason or resubmit.',
    'escalated': 'Case escalated for AICTE Bureau review; awaiting administrative decision.',
    'expired': 'FDR has expired. Contact AICTE immediately to submit replacement or regularization.',
    'completed': 'FDR lifecycle completed. Record archived.',
}


def derive_next_action(lifecycle_state: str) -> str:
    """Deterministic lookup: answers about next action match state table 100% on test cases."""
    normalized = (lifecycle_state or 'submitted').lower().strip()
    return LIFECYCLE_NEXT_ACTIONS.get(
        normalized,
        'Wait for AICTE review; check your institution dashboard for status updates.'
    )


# ---------------------------------------------------------------------------
# Step 10.2: Institution-Scoped Tools
# ---------------------------------------------------------------------------

async def _scoped_fdr_lookup(session: AsyncSession, institution_id: int, fdr_ref: str) -> Optional[FDR]:
    """Look up FDR strictly scoped to caller's institution (adversarial IDOR protection)."""
    norm = fdr_ref.replace('-', '').replace('_', '').strip().casefold()
    candidates = list((await session.scalars(
        select(FDR).where(
            FDR.institution_id == institution_id,
            FDR.fdr_number.ilike(f"%{fdr_ref.strip()}%")
        ).limit(10)
    )).all())
    for f in candidates:
        if f.fdr_number.replace('-', '').replace('_', '').casefold() == norm:
            return f
    return candidates[0] if candidates else None


async def get_case_state(session: AsyncSession, institution_id: int, fdr_ref: str) -> dict:
    """Tool 1: get_case_state for an FDR belonging to the caller's institution."""
    fdr = await _scoped_fdr_lookup(session, institution_id, fdr_ref)
    if not fdr:
        return {'found': False, 'message': f'FDR reference "{fdr_ref}" not found in your institution records.'}

    wf = await session.scalar(
        select(WorkflowInstance).where(WorkflowInstance.fdr_id == fdr.id)
        .order_by(WorkflowInstance.execution_version.desc()).limit(1)
    )
    lifecycle = wf.lifecycle_state if wf else (fdr.lifecycle_state or fdr.status)
    execution = wf.execution_state if wf else fdr.execution_state
    next_action = derive_next_action(lifecycle)

    return {
        'found': True,
        'fdr_number': fdr.fdr_number,
        'bank_name': fdr.bank_name or 'not found in document',
        'amount': float(fdr.amount) if fdr.amount is not None else 'not found in document',
        'maturity_date': fdr.maturity_date.isoformat() if fdr.maturity_date else 'not found in document',
        'lifecycle_state': lifecycle,
        'execution_state': execution,
        'trust_badge': fdr.trust_badge,
        'is_synthetic': fdr.is_synthetic,
        'next_action': next_action,
    }


async def list_required_actions(session: AsyncSession, institution_id: int) -> dict:
    """Tool 2: list_required_actions for caller's institution."""
    query = (
        select(FDR, WorkflowInstance)
        .outerjoin(WorkflowInstance, WorkflowInstance.fdr_id == FDR.id)
        .where(FDR.institution_id == institution_id)
        .order_by(FDR.maturity_date)
    )
    rows = (await session.execute(query.limit(100))).all()
    actions = []
    for fdr, wf in rows:
        lifecycle = wf.lifecycle_state if wf else (fdr.lifecycle_state or fdr.status)
        if lifecycle in {'correction_required', 'validation_failed', 'awaiting_institution', 'renewal_required', 'expired'}:
            actions.append({
                'fdr_number': fdr.fdr_number,
                'is_synthetic': fdr.is_synthetic,
                'lifecycle_state': lifecycle,
                'required_action': derive_next_action(lifecycle),
                'maturity_date': fdr.maturity_date.isoformat() if fdr.maturity_date else None,
            })
    return {'action_count': len(actions), 'required_actions': actions}


async def explain_discrepancy(session: AsyncSession, institution_id: int, fdr_ref: str) -> dict:
    """Tool 3: explain_discrepancy for an FDR belonging to the caller's institution."""
    fdr = await _scoped_fdr_lookup(session, institution_id, fdr_ref)
    if not fdr:
        return {'found': False, 'message': f'FDR "{fdr_ref}" not found in your institution records.'}

    # Query discrepancies
    disc_rows = list((await session.scalars(
        select(Discrepancy).where(Discrepancy.fdr_id == fdr.id)
    )).all())

    # Query correction request
    corr = await session.scalar(
        select(CorrectionRequest).where(
            CorrectionRequest.fdr_id == fdr.id,
            CorrectionRequest.status == 'open'
        ).order_by(CorrectionRequest.id.desc()).limit(1)
    )

    items = []
    for d in disc_rows:
        items.append({
            'field': d.field_name,
            'declared_value': d.declared_value or 'not found in document',
            'extracted_value': d.extracted_value or 'not found in document',
            'severity': d.severity,
        })

    explanation = 'No discrepancies recorded.' if not items else f'Found {len(items)} discrepancy observation(s).'
    return {
        'found': True,
        'fdr_number': fdr.fdr_number,
        'is_synthetic': fdr.is_synthetic,
        'discrepancies': items,
        'explanation': explanation,
        'correction_instructions': corr.reason if corr else ('Please upload a clear scanned FDR receipt with matching details.' if items else None),
        'due_at': corr.due_at.isoformat() if corr and corr.due_at else None,
    }


async def get_deadlines(session: AsyncSession, institution_id: int) -> dict:
    """Tool 4: get_deadlines for caller's institution."""
    today = business_today()
    soon = today + timedelta(days=90)
    
    # 1. Maturing FDRs
    fdr_query = select(FDR).where(
        FDR.institution_id == institution_id,
        FDR.maturity_date >= today,
        FDR.maturity_date <= soon
    ).order_by(FDR.maturity_date)
    maturing = list((await session.scalars(fdr_query.limit(50))).all())

    # 2. Open correction requests
    now = datetime.now(timezone.utc)
    corr_query = select(CorrectionRequest, FDR).join(FDR, FDR.id == CorrectionRequest.fdr_id).where(
        FDR.institution_id == institution_id,
        CorrectionRequest.status == 'open',
        CorrectionRequest.due_at.is_not(None)
    ).order_by(CorrectionRequest.due_at)
    corrs = (await session.execute(corr_query.limit(50))).all()

    deadlines = []
    for f in maturing:
        days_left = (f.maturity_date - today).days
        deadlines.append({
            'type': 'maturity',
            'fdr_number': f.fdr_number,
            'is_synthetic': f.is_synthetic,
            'due_date': f.maturity_date.isoformat(),
            'days_remaining': days_left,
            'action': 'Submit renewal request if extending program approval.'
        })
    for c, f in corrs:
        due = c.due_at
        deadlines.append({
            'type': 'correction_sla',
            'fdr_number': f.fdr_number,
            'is_synthetic': f.is_synthetic,
            'due_date': due.isoformat(),
            'action': f'Submit corrected FDR receipt ({c.reason})'
        })

    return {'total_deadlines': len(deadlines), 'deadlines': deadlines}


def get_renewal_requirements() -> dict:
    """Tool 5: AICTE policy on FDR renewals."""
    return {
        'policy_summary': 'AICTE requires FDRs to remain valid throughout program tenure. Renewal must be requested before maturity.',
        'requirements': [
            'Replacement FDR scan issued by a scheduled commercial bank',
            'Joint lien created in favor of the Regional Officer, AICTE',
            'Amount must match or exceed the minimum prescribed corpus',
            'Tenure minimum 5 years or remaining program duration',
            'Bank verification certificate or confirmation letter',
        ],
        'procedure': 'Go to Institution Portal -> FDRs -> Select maturing FDR -> Request Renewal -> Upload new receipt scan.'
    }


def get_release_requirements() -> dict:
    """Tool 6: AICTE policy on FDR release/refund."""
    return {
        'policy_summary': 'Release/refund of FDR corpus is permissible after completion of the statutory lock-in period and regulatory compliance.',
        'requirements': [
            'Mandatory lock-in period (typically 8–10 years) fulfilled',
            'No pending complaints or non-compliance notices from AICTE',
            'Submission of AICTE Approval Bureau clearance',
            'Formal refund application with original bank account details',
        ],
        'procedure': 'Submit Release/Refund Claim in the Portal -> Bureau Review -> Bureau Chief authorized release decision.'
    }


# ---------------------------------------------------------------------------
# Step 10.1 & 10.5: Context Builder & Guardrails
# ---------------------------------------------------------------------------

async def build_institution_context(session: AsyncSession, institution_id: int) -> dict:
    """Context built server-side from the caller's own cases only."""
    cases = list((await session.scalars(
        select(FDR).where(FDR.institution_id == institution_id).order_by(FDR.created_at.desc()).limit(20)
    )).all())

    summaries = []
    for c in cases:
        wf = await session.scalar(
            select(WorkflowInstance).where(WorkflowInstance.fdr_id == c.id)
            .order_by(WorkflowInstance.execution_version.desc()).limit(1)
        )
        lifecycle = wf.lifecycle_state if wf else (c.lifecycle_state or c.status)
        summaries.append({
            'fdr_number': c.fdr_number,
            'bank': c.bank_name or 'not found in document',
            'amount': float(c.amount) if c.amount else 0.0,
            'maturity_date': c.maturity_date.isoformat() if c.maturity_date else 'not found in document',
            'lifecycle_state': lifecycle,
            'next_action': derive_next_action(lifecycle),
            'is_synthetic': c.is_synthetic,
        })

    return {'institution_id': institution_id, 'cases': summaries}


def enforce_guardrails(text: str) -> str:
    """Step 10.5 & 10.6 Guardrails:
    - No authenticity claims: never say 'this FDR is genuine'
    - No invented values: say 'not found in document'
    - DAGMM surfaces only as 'unusual pattern — review suggested', never rejection.
    """
    out = text
    # Guardrail 1: Authenticity claims filter
    out = re.sub(
        r'\b(this\s+(fdr|receipt|document)\s+is\s+(genuine|authentic|valid|verified\s+authentic))\b',
        'the records do not establish authenticity; review the submitted details',
        out,
        flags=re.I
    )
    out = re.sub(
        r'\b100%\s+(genuine|authentic)\b',
        'authenticity is not established by these records',
        out,
        flags=re.I
    )

    # Guardrail 2: Missing fields
    out = re.sub(r'\b(N/A|null|None|unknown)\b', 'not found in document', out)

    # Guardrail 3: DAGMM anomaly note
    out = re.sub(
        r'\b(rejected\s+due\s+to\s+anomaly|fraud\s+detected)\b',
        'unusual pattern — review suggested',
        out,
        flags=re.I
    )

    return out


# ---------------------------------------------------------------------------
# Message Handler Pipeline
# ---------------------------------------------------------------------------

async def process_institution_message(session: AsyncSession, actor_user, message: str, fdr_ref: Optional[str] = None) -> dict:
    """Step 10.1: POST /institution/assistant/messages handler."""
    institution_id = actor_user.institution_id
    if not institution_id:
        raise PermissionDenied('User is not associated with an institution.')

    raw = message.strip()
    low = raw.casefold()

    # Extract FDR reference from message if not explicitly provided
    if not fdr_ref:
        m = re.search(r'\bFDR[-_ ]?[A-Za-z0-9-]+\b', raw, re.I)
        if m:
            fdr_ref = re.sub(r'\s+', '', m.group(0)).replace('_', '-')

    tool_used = None
    next_action = None
    reply = ""

    # Route request to appropriate institution tool
    if 'deadline' in low or 'due date' in low or 'when' in low and 'expire' in low:
        tool_used = 'get_deadlines'
        res = await get_deadlines(session, institution_id)
        if res['total_deadlines'] == 0:
            reply = "You currently have no upcoming deadlines or open correction requests within the next 90 days."
        else:
            lines = [f"• {d['fdr_number']}{' [SYNTHETIC DEMO]' if d.get('is_synthetic') else ''} ({d['type']}): Due on {d['due_date']} — {d['action']}" for d in res['deadlines']]
            reply = f"Here are your upcoming deadlines:\n" + "\n".join(lines)

    elif 'discrepanc' in low or 'mismatch' in low or 'why' in low and 'correction' in low:
        tool_used = 'explain_discrepancy'
        if fdr_ref:
            res = await explain_discrepancy(session, institution_id, fdr_ref)
            if not res['found']:
                reply = res['message']
            elif not res['discrepancies']:
                reply = f"No discrepancies are flagged for {fdr_ref}. The document details match declared values."
            else:
                disc_text = "\n".join([f"• Field '{d['field']}': Declared was '{d['declared_value']}' but scan showed '{d['extracted_value']}' (Severity: {d['severity']})" for d in res['discrepancies']])
                origin_note=' This is synthetic demo data, not a real institution record.' if res.get('is_synthetic') is True else ''
                reply = f"Discrepancies found for {fdr_ref}.{origin_note}\n{disc_text}\n\nCorrection instruction: {res['correction_instructions']}"
        else:
            reply = "Please specify an FDR number (e.g. FDR-1024) to explain its discrepancies."

    elif 'action' in low or 'next step' in low or 'what' in low and 'do' in low or 'status' in low or 'state' in low:
        tool_used = 'get_case_state'
        if fdr_ref:
            res = await get_case_state(session, institution_id, fdr_ref)
            if not res['found']:
                reply = res['message']
            else:
                next_action = res['next_action']
                reply = (
                    f"Status for {res['fdr_number']}:\n"
                    f"• Data origin: {'SYNTHETIC DEMO — not a real institution record' if res.get('is_synthetic') is True else 'Institution record' if res.get('is_synthetic') is False else 'Origin unclassified'}\n"
                    f"• Lifecycle State: {res['lifecycle_state']}\n"
                    f"• Bank: {res['bank_name']}\n"
                    f"• Amount: INR {res['amount']}\n"
                    f"• Maturity Date: {res['maturity_date']}\n\n"
                    f"Recommended next action: {next_action}"
                )
        else:
            tool_used = 'list_required_actions'
            res = await list_required_actions(session, institution_id)
            if res['action_count'] == 0:
                reply = "All your submitted FDRs are in order. No action is currently required from your institution."
            else:
                lines = [f"• {a['fdr_number']}{' [SYNTHETIC DEMO]' if a.get('is_synthetic') else ''} ({a['lifecycle_state']}): {a['required_action']}" for a in res['required_actions']]
                reply = f"The following cases require your attention:\n" + "\n".join(lines)

    elif 'renewal' in low or 'renew' in low:
        tool_used = 'get_renewal_requirements'
        reqs = get_renewal_requirements()
        reply = (
            f"{reqs['policy_summary']}\n\n"
            f"Requirements:\n" + "\n".join([f"• {r}" for r in reqs['requirements']]) +
            f"\n\nHow to submit: {reqs['procedure']}"
        )

    elif 'release' in low or 'refund' in low:
        tool_used = 'get_release_requirements'
        reqs = get_release_requirements()
        reply = (
            f"{reqs['policy_summary']}\n\n"
            f"Requirements:\n" + "\n".join([f"• {r}" for r in reqs['requirements']]) +
            f"\n\nProcedure: {reqs['procedure']}"
        )

    else:
        # General guidance
        tool_used = 'list_required_actions'
        res = await list_required_actions(session, institution_id)
        reply = (
            "I am your AICTE Institution Assistance Agent. I can help you track case states, "
            "explain document discrepancies, view upcoming renewal/correction deadlines, "
            "and guide you through renewal and release requirements. How can I assist with your FDRs today?"
        )

    # Ask the configured LLM to phrase a grounded answer from server-derived tool
    # results. If the provider is unavailable, keep the deterministic reply.
    if get_settings().command_llm_enabled:
        try:
            sanitized_reply = await generate_grounded_reply(raw, tool_used, res if 'res' in locals() else reqs, reply)
        except Exception:
            sanitized_reply = reply
    else:
        sanitized_reply = reply

    # Apply guardrails to both generated and deterministic replies.
    sanitized_reply = enforce_guardrails(sanitized_reply)

    return {
        'reply': sanitized_reply,
        'tool_used': tool_used,
        'next_action': next_action,
        'fdr_ref': fdr_ref,
    }
