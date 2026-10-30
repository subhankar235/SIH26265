from pydantic import BaseModel, ConfigDict, field_validator
from email_validator import validate_email, EmailNotValidError

class InstitutionCreate(BaseModel):
    aicte_id: str
    name: str
    state: str
    head_name: str
    contact_email: str
    contact_phone: str

    @field_validator('contact_email')
    @classmethod
    def normalize_contact_email(cls, value):
        try:
            return validate_email(value, check_deliverability=False, test_environment=True).normalized.lower()
        except EmailNotValidError as exc:
            raise ValueError('Enter a valid email address.') from exc

class InstitutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    aicte_id: str
    name: str
    state: str
    head_name: str
    contact_email: str
    contact_phone: str
    telegram_chat_id: str | None = None
    fdr_count: int = 0
    total_value: float = 0

class AssistantMessageRequest(BaseModel):
    message: str
    fdr_ref: str | None = None

class AssistantMessageResponse(BaseModel):
    reply: str
    tool_used: str | None = None
    next_action: str | None = None
    fdr_ref: str | None = None
