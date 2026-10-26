from typing import Annotated, Literal
from email_validator import validate_email as _validate_email, EmailNotValidError
from pydantic import AfterValidator, BaseModel, Field, ConfigDict


def _normalized_email(value: str) -> str:
    try:
        return _validate_email(value, check_deliverability=False, test_environment=True).normalized.lower()
    except EmailNotValidError as exc:
        raise ValueError('Enter a valid email address.') from exc


EmailAddress = Annotated[str, AfterValidator(_normalized_email)]


class LoginRequest(BaseModel):
    email: EmailAddress
    password: str = Field(min_length=1, max_length=256)


class MfaVerifyRequest(BaseModel):
    code: str = Field(pattern=r'^\d{6}$')


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=128)


class InstitutionRegistrationRequest(BaseModel):
    institution_name: str = Field(min_length=2, max_length=255)
    aicte_institution_id: str = Field(min_length=2, max_length=50)
    contact_name: str = Field(min_length=2, max_length=255)
    email: EmailAddress
    phone: str = Field(min_length=7, max_length=32)
    state: str = Field(min_length=2, max_length=100)
    address: str | None = Field(default=None, max_length=500)
    password: str = Field(min_length=12, max_length=128)


class OfficialRegistrationRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    email: EmailAddress
    password: str = Field(min_length=12, max_length=128)


class TokenBody(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class ResetPasswordRequest(TokenBody):
    new_password: str = Field(min_length=12, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailAddress


class InviteAcceptRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    password: str = Field(min_length=12, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class AdminUserCreate(BaseModel):
    email: EmailAddress
    full_name: str = Field(min_length=2, max_length=255)
    role: str
    institution_id: int | None = None


class AdminUserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    role: str | None = None
    institution_id: int | None = None


class RegistrationDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class RegistrationDecisionRequest(BaseModel):
    decision: Literal['approve', 'reject']
    reason: str = Field(min_length=4, max_length=1000)


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    full_name: str
    role: str
    institution_id: int | None
    status: str
    must_change_password: bool
    failed_login_count: int
