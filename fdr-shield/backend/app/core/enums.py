"""Shared enums (single source of truth for statuses, roles, badges)."""

from enum import Enum


class Role(str, Enum):
    INSTITUTION = 'institution'
    SCRUTINY_OFFICER = 'scrutiny_officer'
    BUREAU_CHIEF = 'bureau_chief'
    ADMIN = 'admin'


class FDRStatus(str, Enum):
    SUBMITTED = 'submitted'
    UNDER_SCRUTINY = 'under_scrutiny'
    VERIFIED = 'verified'
    MISMATCH = 'mismatch'
    RENEWAL_REQUESTED = 'renewal_requested'
    EXPIRED = 'expired'
    RELEASE_REQUESTED = 'release_requested'
    RELEASED = 'released'


class TrustBadge(str, Enum):
    BANK_VERIFIED = 'bank_verified'      # green
    SELF_DECLARED = 'self_declared'      # yellow
    MISMATCH = 'mismatch'                # red


class AlertStage(str, Enum):
    T_90 = 'T-90'
    T_30 = 'T-30'
    T_0 = 'T-0'
    ESCALATED = 'escalated'
