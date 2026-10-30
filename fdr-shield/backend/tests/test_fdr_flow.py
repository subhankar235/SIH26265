from app.services.fdr_service import ALLOWED_TRANSITIONS
from app.core.enums import FDRStatus

def test_fdr_state_machine_allows_review_and_release_path():
    assert FDRStatus.UNDER_SCRUTINY.value in ALLOWED_TRANSITIONS[FDRStatus.SUBMITTED.value]
    assert FDRStatus.VERIFIED.value in ALLOWED_TRANSITIONS[FDRStatus.UNDER_SCRUTINY.value]
    assert FDRStatus.RELEASED.value in ALLOWED_TRANSITIONS[FDRStatus.RELEASE_REQUESTED.value]
    assert FDRStatus.RELEASED.value not in ALLOWED_TRANSITIONS[FDRStatus.SUBMITTED.value]
