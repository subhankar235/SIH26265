"""Mapping functions between legacy status and orthogonal status dimensions.

Dimensions:
- lifecycle_state: Business stage
- execution_state: Workflow engine state
- authorization_state: Human gate / approval state
- verification_level: Trust level of the data
"""
from __future__ import annotations
from typing import Any
from app.core.enums import (
    FDRStatus,
    LifecycleState,
    ExecutionState,
    AuthorizationState,
    VerificationLevel,
    TrustBadge,
)


def normalize_enum_val(val: Any) -> str:
    if val is None:
        return ''
    if hasattr(val, 'value'):
        val = val.value
    return str(val).lower()


def map_legacy_status_to_dimensions(
    legacy_status: str | FDRStatus,
    trust_badge: str | TrustBadge | None = None,
) -> dict[str, str]:
    """Map flat legacy FDRStatus string to the 4 orthogonal dimensions."""
    s = normalize_enum_val(legacy_status)
    b = normalize_enum_val(trust_badge)

    if s == FDRStatus.SUBMITTED.value:
        return {
            'lifecycle_state': LifecycleState.SUBMITTED.value,
            'execution_state': ExecutionState.COMPLETED.value,
            'authorization_state': AuthorizationState.PENDING.value,
            'verification_level': VerificationLevel.DECLARED.value,
        }
    elif s == FDRStatus.UNDER_SCRUTINY.value:
        return {
            'lifecycle_state': LifecycleState.UNDER_REVIEW.value,
            'execution_state': ExecutionState.WAITING_HUMAN.value,
            'authorization_state': AuthorizationState.PENDING.value,
            'verification_level': VerificationLevel.EXTRACTED.value,
        }
    elif s == FDRStatus.VERIFIED.value:
        v_level = (
            VerificationLevel.MOCK_VERIFIED.value
            if b == TrustBadge.BANK_VERIFIED.value
            else VerificationLevel.HUMAN_SCRUTINIZED.value
        )
        return {
            'lifecycle_state': LifecycleState.ACCEPTED.value,
            'execution_state': ExecutionState.COMPLETED.value,
            'authorization_state': AuthorizationState.APPROVED.value,
            'verification_level': v_level,
        }
    elif s == FDRStatus.MISMATCH.value:
        return {
            'lifecycle_state': LifecycleState.VALIDATION_FAILED.value,
            'execution_state': ExecutionState.WAITING_HUMAN.value,
            'authorization_state': AuthorizationState.REJECTED.value,
            'verification_level': VerificationLevel.EXTRACTED.value,
        }
    elif s == FDRStatus.RENEWAL_REQUESTED.value:
        return {
            'lifecycle_state': LifecycleState.RENEWAL_REQUIRED.value,
            'execution_state': ExecutionState.WAITING_HUMAN.value,
            'authorization_state': AuthorizationState.PENDING.value,
            'verification_level': VerificationLevel.MOCK_VERIFIED.value,
        }
    elif s == FDRStatus.EXPIRED.value:
        return {
            'lifecycle_state': LifecycleState.ESCALATED.value,
            'execution_state': ExecutionState.COMPLETED.value,
            'authorization_state': AuthorizationState.NOT_REQUIRED.value,
            'verification_level': VerificationLevel.MOCK_VERIFIED.value,
        }
    elif s == FDRStatus.RELEASE_REQUESTED.value:
        return {
            'lifecycle_state': LifecycleState.RELEASE_REQUESTED.value,
            'execution_state': ExecutionState.WAITING_HUMAN.value,
            'authorization_state': AuthorizationState.PENDING.value,
            'verification_level': VerificationLevel.MOCK_VERIFIED.value,
        }
    elif s == FDRStatus.RELEASED.value:
        return {
            'lifecycle_state': LifecycleState.RELEASE_APPROVED.value,
            'execution_state': ExecutionState.COMPLETED.value,
            'authorization_state': AuthorizationState.APPROVED.value,
            'verification_level': VerificationLevel.MOCK_VERIFIED.value,
        }
    else:
        # Fallback for unmapped or new status
        return {
            'lifecycle_state': LifecycleState.SUBMITTED.value,
            'execution_state': ExecutionState.COMPLETED.value,
            'authorization_state': AuthorizationState.PENDING.value,
            'verification_level': VerificationLevel.DECLARED.value,
        }


def map_dimensions_to_legacy_status(
    lifecycle_state: str | LifecycleState,
    authorization_state: str | AuthorizationState | None = None,
) -> str:
    """Map new lifecycle_state back to legacy flat status for backward compatibility."""
    ls = normalize_enum_val(lifecycle_state)

    if ls in {
        LifecycleState.SUBMITTED.value,
        LifecycleState.EXTRACTION_PENDING.value,
        LifecycleState.EXTRACTING.value,
        LifecycleState.VALIDATION_PENDING.value,
    }:
        return FDRStatus.SUBMITTED.value

    elif ls in {
        LifecycleState.READY_FOR_SCRUTINY.value,
        LifecycleState.UNDER_REVIEW.value,
        LifecycleState.AWAITING_OFFICIAL_DECISION.value,
    }:
        return FDRStatus.UNDER_SCRUTINY.value

    elif ls == LifecycleState.ACCEPTED.value:
        return FDRStatus.VERIFIED.value

    elif ls in {
        LifecycleState.VALIDATION_FAILED.value,
        LifecycleState.CORRECTION_REQUIRED.value,
        LifecycleState.AWAITING_INSTITUTION.value,
    }:
        return FDRStatus.MISMATCH.value

    elif ls in {
        LifecycleState.RENEWAL_REQUIRED.value,
        LifecycleState.RENEWED.value,
    }:
        return FDRStatus.RENEWAL_REQUESTED.value

    elif ls in {
        LifecycleState.RELEASE_REQUESTED.value,
        LifecycleState.AWAITING_RELEASE_DECISION.value,
    }:
        return FDRStatus.RELEASE_REQUESTED.value

    elif ls == LifecycleState.RELEASE_APPROVED.value:
        return FDRStatus.RELEASED.value

    elif ls == LifecycleState.RELEASE_REJECTED.value:
        return FDRStatus.VERIFIED.value

    elif ls in {
        LifecycleState.ESCALATED.value,
        LifecycleState.EXPIRED.value,
        LifecycleState.COMPLETED.value,
    }:
        return FDRStatus.EXPIRED.value

    return FDRStatus.SUBMITTED.value


def sync_fdr_dimensions(fdr: Any) -> None:
    """Synchronize flat status and orthogonal dimensions on an FDR instance."""
    # If dimensions are not set, derive from status
    if not getattr(fdr, 'lifecycle_state', None) and getattr(fdr, 'status', None):
        dims = map_legacy_status_to_dimensions(fdr.status, getattr(fdr, 'trust_badge', None))
        fdr.lifecycle_state = dims['lifecycle_state']
        fdr.execution_state = dims['execution_state']
        fdr.authorization_state = dims['authorization_state']
        fdr.verification_level = dims['verification_level']
    elif getattr(fdr, 'lifecycle_state', None) and not getattr(fdr, 'status', None):
        fdr.status = map_dimensions_to_legacy_status(fdr.lifecycle_state, getattr(fdr, 'authorization_state', None))
