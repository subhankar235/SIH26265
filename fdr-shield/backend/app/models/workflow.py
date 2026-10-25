"""Persistent workflow, human-decision and operational records.

The FDR remains the business record. These tables store execution and authorization
state separately so worker progress never has to overwrite FDR business history.
"""
from datetime import datetime, timezone
from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Index,
    Float, Integer, JSON, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


LIFECYCLE_VALUES = (
    'submitted','extraction_pending','extracting','validation_pending','validation_failed',
    'correction_required','awaiting_institution','ready_for_scrutiny','under_review',
    'awaiting_official_decision','accepted','renewal_required','renewed','release_requested',
    'awaiting_release_decision','release_approved','release_rejected','escalated','expired','completed')
EXECUTION_VALUES = (
    'not_started','running','waiting_event','waiting_timer','waiting_human','paused',
    'retrying','failed','blocked','cancelled','completed')
AUTHORIZATION_VALUES = ('not_required','pending','approved','rejected')
VERIFICATION_VALUES = ('declared','extracted','mock_verified','verified_external','ai_recommendation','human_scrutinized')


class WorkflowInstance(Base):
    __tablename__ = 'workflow_instances'
    __table_args__ = (
        UniqueConstraint('fdr_id', 'execution_version', name='uq_workflow_fdr_execution_version'),
        CheckConstraint("lifecycle_state IN (" + ','.join(repr(v) for v in LIFECYCLE_VALUES) + ")", name='ck_workflow_lifecycle'),
        CheckConstraint("execution_state IN (" + ','.join(repr(v) for v in EXECUTION_VALUES) + ")", name='ck_workflow_execution'),
        CheckConstraint("authorization_state IN (" + ','.join(repr(v) for v in AUTHORIZATION_VALUES) + ")", name='ck_workflow_authorization'),
        Index('ix_workflow_state_wake', 'execution_state', 'next_wake_at'),
        Index('ix_workflow_institution_lifecycle', 'institution_id', 'lifecycle_state'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    fdr_id: Mapped[int] = mapped_column(ForeignKey('fdrs.id'), nullable=False, index=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey('institutions.id'), nullable=False, index=True)
    workflow_version: Mapped[str] = mapped_column(String(80), default='fdr-case-v1')
    execution_version: Mapped[int] = mapped_column(Integer, default=1)
    lifecycle_state: Mapped[str] = mapped_column(String(40), nullable=False)
    execution_state: Mapped[str] = mapped_column(String(32), nullable=False, default='not_started')
    authorization_state: Mapped[str] = mapped_column(String(24), nullable=False, default='not_required')
    current_node: Mapped[str | None] = mapped_column(String(100), nullable=True)
    paused_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    paused_from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    next_wake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    replay_document_id: Mapped[int | None] = mapped_column(ForeignKey('documents.id'), nullable=True)
    replay_from_execution_id: Mapped[int | None] = mapped_column(ForeignKey('workflow_node_executions.id'), nullable=True)
    replay_requested_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    replay_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_input_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    retry_parent_execution_id: Mapped[int | None] = mapped_column(ForeignKey('workflow_node_executions.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class VerificationRun(Base):
    """Immutable, source-labelled snapshot of one OCR/bank comparison pass."""
    __tablename__ = 'verification_runs'
    __table_args__ = (Index('ix_verification_runs_fdr_created', 'fdr_id', 'created_at'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    fdr_id: Mapped[int] = mapped_column(ForeignKey('fdrs.id'), nullable=False)
    document_id: Mapped[int | None] = mapped_column(ForeignKey('documents.id'), nullable=True)
    extraction_engine: Mapped[str] = mapped_column(String(80), nullable=False)
    engine_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    verification_level: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    declared_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    extracted_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    bank_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    discrepancies: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WorkflowNodeExecution(Base):
    __tablename__ = 'workflow_node_executions'
    __table_args__ = (
        UniqueConstraint('workflow_instance_id','node_key','attempt',name='uq_workflow_node_attempt'),
        CheckConstraint("status IN ('pending','running','succeeded','failed','skipped','cancelled')", name='ck_node_execution_status'),
        Index('ix_node_execution_instance_started', 'workflow_instance_id', 'started_at'),
        Index('ix_node_execution_status', 'status'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_instance_id: Mapped[int] = mapped_column(ForeignKey('workflow_instances.id'), nullable=False)
    node_key: Mapped[str] = mapped_column(String(100), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    parent_execution_id: Mapped[int | None] = mapped_column(ForeignKey('workflow_node_executions.id'), nullable=True)
    replay_of_id: Mapped[int | None] = mapped_column(ForeignKey('workflow_node_executions.id'), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='pending')
    input_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnostics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rule_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    workflow_version: Mapped[str] = mapped_column(String(80), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(24), default='system')
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkflowEvent(Base):
    __tablename__ = 'workflow_events'
    __table_args__ = (UniqueConstraint('dedupe_key', name='uq_workflow_event_dedupe'),
        Index('ix_workflow_event_instance_received', 'workflow_instance_id', 'received_at'))
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_instance_id: Mapped[int] = mapped_column(ForeignKey('workflow_instances.id'), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowCheckpoint(Base):
    __tablename__ = 'workflow_checkpoints'
    __table_args__ = (Index('ix_checkpoint_instance_created', 'workflow_instance_id', 'created_at'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_instance_id: Mapped[int] = mapped_column(ForeignKey('workflow_instances.id'), nullable=False)
    node_execution_id: Mapped[int | None] = mapped_column(ForeignKey('workflow_node_executions.id'), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    state_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OutboxEvent(Base):
    __tablename__ = 'outbox_events'
    __table_args__ = (UniqueConstraint('idempotency_key', name='uq_outbox_idempotency'),
        CheckConstraint("status IN ('pending','processing','sent','failed','dead')", name='ck_outbox_status'),
        Index('ix_outbox_status_available', 'status', 'next_attempt_at'))
    id: Mapped[int] = mapped_column(primary_key=True)
    aggregate_id: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default='pending')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalRecord(Base):
    __tablename__ = 'approval_records'
    __table_args__ = (CheckConstraint("decision IN ('approve','reject','request_correction','escalate')", name='ck_approval_decision'),
        Index('ix_approval_instance_created', 'workflow_instance_id', 'created_at'),
        UniqueConstraint('idempotency_key', name='uq_approval_idempotency'))
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_instance_id: Mapped[int] = mapped_column(ForeignKey('workflow_instances.id'), nullable=False)
    fdr_id: Mapped[int] = mapped_column(ForeignKey('fdrs.id'), nullable=False)
    refund_request_id: Mapped[int | None] = mapped_column(ForeignKey('refund_requests.id'), nullable=True)
    request_type: Mapped[str] = mapped_column(String(40), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    source_audit_id: Mapped[int | None] = mapped_column(ForeignKey('audit_logs.id'), unique=True, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recommendation_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExceptionItem(Base):
    __tablename__ = 'exception_items'
    __table_args__ = (CheckConstraint("status IN ('open','claimed','resolved')", name='ck_exception_status'),
        Index('ix_exception_status_due', 'status', 'due_at'))
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_instance_id: Mapped[int] = mapped_column(ForeignKey('workflow_instances.id'), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default='open')
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CorrectionRequest(Base):
    __tablename__ = 'correction_requests'
    __table_args__ = (CheckConstraint("status IN ('open','submitted','accepted','rejected','expired')", name='ck_correction_status'),
        Index('ix_correction_status_due', 'status', 'due_at'))
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_instance_id: Mapped[int] = mapped_column(ForeignKey('workflow_instances.id'), nullable=False)
    fdr_id: Mapped[int] = mapped_column(ForeignKey('fdrs.id'), nullable=False)
    requested_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    required_fields: Mapped[list] = mapped_column(JSON, default=list)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default='open')
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AutomationRule(Base):
    __tablename__ = 'automation_rules'
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AutomationRuleVersion(Base):
    __tablename__ = 'automation_rule_versions'
    __table_args__ = (UniqueConstraint('rule_id','version',name='uq_rule_version'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey('automation_rules.id'), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    policy: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CommandExecution(Base):
    __tablename__ = 'command_executions'
    __table_args__ = (CheckConstraint("status IN ('planned','confirmed','running','succeeded','failed','cancelled')", name='ck_command_status'),
        UniqueConstraint('idempotency_key',name='uq_command_idempotency'),
        Index('ix_command_actor_created', 'user_id', 'created_at'))
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    raw_command: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    interpreted_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    plan_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    authorization_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default='planned')
    steps: Mapped[list] = mapped_column(JSON, default=list)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class NotificationDeliveryAttempt(Base):
    __tablename__ = 'notification_delivery_attempts'
    __table_args__ = (UniqueConstraint('notification_id','attempt_no',name='uq_notification_attempt'),
        Index('ix_notification_attempt_status', 'status'))
    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey('notifications.id'), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    template_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
