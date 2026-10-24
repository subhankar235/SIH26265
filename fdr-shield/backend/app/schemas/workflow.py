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
    text: str = Field(min_length=3,max_length=2000)
    idempotency_key: str = Field(min_length=8,max_length=255)


class CommandConfirmRequest(BaseModel):
    plan_hash: str = Field(min_length=32,max_length=64)


class CommandCancelRequest(BaseModel):
    reason: str = Field(min_length=4,max_length=1000)


class CommandIntentModel(BaseModel):
    """Strict allowlisted intent contract used after deterministic/LLM parsing."""
    model_config = ConfigDict(extra='forbid')
    intent: Literal['find_maturing','list_by_state','list_overdue','list_awaiting_approval',
        'explain_blocked','summarize_failed_notifications','pause_case','resume_case',
        'recheck_document','retry_node']
    args: dict[str,Any]
    confidence: float = Field(default=1.0,ge=0,le=1)

    @model_validator(mode='after')
    def validate_arguments(self):
        requirements={
            'find_maturing':{'days':int},'list_by_state':{'state':str},'list_overdue':{},
            'list_awaiting_approval':{},'explain_blocked':{'fdr_ref':str},
            'summarize_failed_notifications':{},'pause_case':{'fdr_ref':str},
            'resume_case':{'fdr_ref':str},'recheck_document':{'fdr_ref':str},
            'retry_node':{'fdr_ref':str}}
        expected=requirements[self.intent]
        if set(self.args)!=set(expected): raise ValueError('Intent args do not match the registered tool schema.')
        for key,kind in expected.items():
            value=self.args[key]
            if kind is int and (isinstance(value,bool) or not isinstance(value,int)):
                raise ValueError(f'{key} must be an integer.')
            if kind is str and not isinstance(value,str): raise ValueError(f'{key} must be text.')
        if self.intent=='find_maturing' and not 1<=self.args['days']<=365:
            raise ValueError('days must be between 1 and 365.')
        if self.intent=='list_by_state' and self.args['state'] not in {
            'submitted','under_review','correction_required','ready_for_scrutiny','accepted',
            'renewal_required','release_requested','awaiting_release_decision','escalated','expired','completed'}:
            raise ValueError('State is not an allowlisted case state.')
        return self
