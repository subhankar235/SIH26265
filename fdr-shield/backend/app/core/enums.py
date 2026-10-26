"""Shared enums (single source of truth for statuses, roles, badges)."""

from enum import Enum


class Role(str, Enum):
    INSTITUTION = 'institution'
    AICTE_OFFICIAL = 'aicte_official'
    ADMIN = 'admin'
    # Compatibility alias: existing rows and tokens store `admin` as Super Admin.
    SUPER_ADMIN = 'admin'


class AccountStatus(str, Enum):
    INVITED = 'invited'
    PENDING_EMAIL_VERIFY = 'pending_email_verify'
    PENDING_APPROVAL = 'pending_approval'
    ACTIVE = 'active'
    LOCKED = 'locked'
    SUSPENDED = 'suspended'
    REJECTED = 'rejected'
    DISABLED = 'disabled'


class FDRStatus(str, Enum):
    SUBMITTED = 'submitted'
    UNDER_SCRUTINY = 'under_scrutiny'
    VERIFIED = 'verified'
    MISMATCH = 'mismatch'
    RENEWAL_REQUESTED = 'renewal_requested'
    EXPIRED = 'expired'
    RELEASE_REQUESTED = 'release_requested'
    RELEASED = 'released'


class LifecycleState(str, Enum):
    SUBMITTED = 'submitted'
    EXTRACTION_PENDING = 'extraction_pending'
    EXTRACTING = 'extracting'
    VALIDATION_PENDING = 'validation_pending'
    VALIDATION_FAILED = 'validation_failed'
    CORRECTION_REQUIRED = 'correction_required'
    AWAITING_INSTITUTION = 'awaiting_institution'
    READY_FOR_SCRUTINY = 'ready_for_scrutiny'
    UNDER_REVIEW = 'under_review'
    AWAITING_OFFICIAL_DECISION = 'awaiting_official_decision'
    ACCEPTED = 'accepted'
    RENEWAL_REQUIRED = 'renewal_required'
    RENEWED = 'renewed'
    RELEASE_REQUESTED = 'release_requested'
    AWAITING_RELEASE_DECISION = 'awaiting_release_decision'
    RELEASE_APPROVED = 'release_approved'
    RELEASE_REJECTED = 'release_rejected'
    ESCALATED = 'escalated'
    EXPIRED = 'expired'
    COMPLETED = 'completed'


class ExecutionState(str, Enum):
    NOT_STARTED = 'not_started'
    RUNNING = 'running'
    WAITING_EVENT = 'waiting_event'
    WAITING_TIMER = 'waiting_timer'
    WAITING_HUMAN = 'waiting_human'
    PAUSED = 'paused'
    RETRYING = 'retrying'
    FAILED = 'failed'
    BLOCKED = 'blocked'
    CANCELLED = 'cancelled'
    COMPLETED = 'completed'


class AuthorizationState(str, Enum):
    NOT_REQUIRED = 'not_required'
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'


class VerificationLevel(str, Enum):
    DECLARED = 'declared'
    EXTRACTED = 'extracted'
    MOCK_VERIFIED = 'mock_verified'
    VERIFIED_EXTERNAL = 'verified_external'
    AI_RECOMMENDATION = 'ai_recommendation'
    HUMAN_SCRUTINIZED = 'human_scrutinized'


class TrustBadge(str, Enum):
    BANK_VERIFIED = 'bank_verified'      # green
    SELF_DECLARED = 'self_declared'      # yellow
    MISMATCH = 'mismatch'                # red


class AlertStage(str, Enum):
    T_90 = 'T-90'
    T_30 = 'T-30'
    T_0 = 'T-0'
    ESCALATED = 'escalated'
