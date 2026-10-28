"""Workflow inspection and execution contracts."""
from datetime import date
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Literal
from pydantic import model_validator


class ExtractedField(BaseModel):
    value: str | Decimal | date | None = None
    confidence: float = Field(ge=0, le=1)
    source_span: str | dict[str, Any] | None = None
    trust: Literal['extracted'] = 'extracted'


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fdr_id: int
    document_id: int
    document_version: int
    raw_ref: str
    extractor_version: str
    fields: dict[str, ExtractedField]
    overall_confidence: float = Field(ge=0, le=1)


class ValidationDiscrepancy(BaseModel):
    field: str
    declared_value: str | None = None
    extracted_value: str | None = None
    source: str = 'validation_rule'
    severity: Literal['low','medium','high']
    rule_id: str
    rule_version: str = 'validation-v1'
    message: str


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    passed: bool
    rule_version: str
    discrepancies: list[ValidationDiscrepancy] = Field(default_factory=list)
    required_fields_missing: list[str] = Field(default_factory=list)


class ReplayRequest(BaseModel):
    checkpoint_id: int
    reason: str = Field(min_length=4, max_length=1000)
    acknowledge_side_effects: bool = False
    idempotency_key: str = Field(min_length=8, max_length=255)


class WorkflowActionRequest(BaseModel):
    reason: str = Field(min_length=4,max_length=1000)
    idempotency_key: str = Field(min_length=8,max_length=255)


class RetryNodeRequest(WorkflowActionRequest):
    acknowledge_side_effects: bool = False


class ApprovalRequest(BaseModel):
    fdr_id: int
    request_type: Literal['fdr_scrutiny','release_refund']
    decision: Literal['approve','reject','request_correction','escalate']
    rationale: str = Field(min_length=4,max_length=2000)
    idempotency_key: str = Field(min_length=8,max_length=255)
    refund_request_id: int | None = None


class ExceptionClaimRequest(BaseModel):
    reason: str = Field(min_length=4,max_length=1000)
    idempotency_key: str = Field(min_length=8,max_length=255)


class ExceptionDecisionRequest(BaseModel):
    decision: Literal['approve','reject','request_correction','escalate']
    rationale: str = Field(min_length=4,max_length=2000)
    idempotency_key: str = Field(min_length=8,max_length=255)


class CommandInterpretRequest(BaseModel):
    text: str = Field(min_length=1,max_length=2000)
    idempotency_key: str = Field(min_length=8,max_length=255)
    conversation_id: str | None = Field(default=None,min_length=8,max_length=64,pattern=r'^[A-Za-z0-9_-]+$')


class CommandConfirmRequest(BaseModel):
    plan_hash: str = Field(min_length=32,max_length=64)


class CommandCancelRequest(BaseModel):
    reason: str = Field(min_length=4,max_length=1000)


class StrictCommandArgs(BaseModel):
    model_config = ConfigDict(extra='forbid')


class CommandIntentModel(BaseModel):
    """Strict allowlisted intent contract used after deterministic/LLM parsing."""
    model_config = ConfigDict(extra='forbid')
    intent: Literal['find_maturing','recheck_document','list_by_state','prepare_reminders',
        'list_overdue','pause_case','resume_case','retry_node','list_awaiting_my_approval',
        'list_awaiting_approval','explain_blocked','explain_case_status',
        'summarize_failed_notifications','escalate_cases','get_fdr_details','get_task_status','count_fdrs',
        'list_recent_fdrs','analyze_maturing_discrepancies','list_unresolved_discrepancies']
    args: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode='after')
    def validate_arguments(self):
        normalized = self.intent.strip().upper()
        allowed_intents = {
            'FIND_MATURING', 'RECHECK_DOCUMENT', 'LIST_BY_STATE', 'PREPARE_REMINDERS',
            'LIST_OVERDUE', 'PAUSE_CASE', 'RESUME_CASE', 'RETRY_NODE',
            'LIST_AWAITING_MY_APPROVAL', 'LIST_AWAITING_APPROVAL', 'EXPLAIN_BLOCKED',
            'EXPLAIN_CASE_STATUS', 'SUMMARIZE_FAILED_NOTIFICATIONS', 'ESCALATE_CASES',
            'GET_FDR_DETAILS', 'GET_TASK_STATUS','COUNT_FDRS', 'LIST_RECENT_FDRS',
            'ANALYZE_MATURING_DISCREPANCIES','LIST_UNRESOLVED_DISCREPANCIES'
        }
        if normalized not in allowed_intents:
            raise ValueError(f'Unsupported command intent: {self.intent}')
        self.intent = normalized.lower()

        requirements = {
            'find_maturing': {'days': int},
            'list_by_state': {'state': str},
            'list_overdue': {},
            'list_awaiting_my_approval': {},
            'list_awaiting_approval': {},
            'explain_blocked': {'fdr_ref': str},
            'explain_case_status': {'fdr_ref': str},
            'get_fdr_details': {'fdr_ref': str},
            'get_task_status': {'command_id':int},
            'count_fdrs': {},
            'list_recent_fdrs': {'limit': int},
            'analyze_maturing_discrepancies': {'days':int,'limit':int},
            'list_unresolved_discrepancies': {'limit':int},
            'summarize_failed_notifications': {},
            'pause_case': {'fdr_ref': str},
            'resume_case': {'fdr_ref': str},
            'recheck_document': {'fdr_ref': (str, list)},
            'retry_node': {'fdr_ref': str},
            'prepare_reminders': {'days': int},
            'escalate_cases': {},
        }
        expected = requirements.get(self.intent, {})
        for key, kind in expected.items():
            if key not in self.args:
                if key == 'days':
                    self.args[key] = 90 if self.intent=='analyze_maturing_discrepancies' else 30
                elif key=='limit' and self.intent in {'analyze_maturing_discrepancies','list_unresolved_discrepancies'}:
                    self.args[key]=100
                elif key == 'state':
                    self.args[key] = 'submitted'
                else:
                    raise ValueError(f'Missing required argument {key} for intent {self.intent}')
            val = self.args[key]
            if isinstance(kind, tuple):
                if not any(isinstance(val, k) for k in kind):
                    raise ValueError(f'{key} must be one of {kind}')
            elif kind is int:
                if isinstance(val, bool) or not isinstance(val, int):
                    raise ValueError(f'{key} must be an integer.')
            elif kind is str:
                if not isinstance(val, str):
                    raise ValueError(f'{key} must be text.')

        if self.intent == 'find_maturing' and not 1 <= self.args.get('days', 30) <= 365:
            raise ValueError('days must be between 1 and 365.')
        if self.intent == 'list_recent_fdrs' and not 1 <= self.args.get('limit', 5) <= 50:
            raise ValueError('limit must be between 1 and 50.')
        if self.intent=='analyze_maturing_discrepancies':
            if not 1<=self.args.get('days',90)<=365:raise ValueError('days must be between 1 and 365.')
            if not 1<=self.args.get('limit',100)<=200:raise ValueError('limit must be between 1 and 200.')
        if self.intent=='list_unresolved_discrepancies' and not 1<=self.args.get('limit',100)<=200:
            raise ValueError('limit must be between 1 and 200.')
        if self.intent == 'list_by_state':
            state_val = self.args.get('state')
            valid_states = {
                'submitted', 'under_review', 'correction_required', 'ready_for_scrutiny',
                'accepted', 'renewal_required', 'release_requested', 'awaiting_release_decision',
                'escalated', 'expired', 'completed', 'waiting_human', 'waiting_my_approval', 'overdue'
            }
            if state_val not in valid_states:
                raise ValueError('State is not an allowlisted case state.')
        return self
