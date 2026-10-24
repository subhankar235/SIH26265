from pydantic import BaseModel
class LoginRequest(BaseModel): email: str; password: str
class TokenResponse(BaseModel): access_token: str|None=None; token_type: str='bearer'; mfa_required: bool=False; temp_token: str|None=None
class MfaVerifyRequest(BaseModel): temp_token: str; code: str
