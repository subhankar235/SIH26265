from pydantic import BaseModel, Field
from app.schemas.auth import EmailAddress


class SuperAdminSetupRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    email: EmailAddress
    phone_number: str = Field(min_length=7, max_length=32, pattern=r'^[+0-9() .-]+$')
    password: str = Field(min_length=12, max_length=128)
    confirm_password: str = Field(min_length=12, max_length=128)
    setup_secret: str = Field(min_length=1, max_length=512)
