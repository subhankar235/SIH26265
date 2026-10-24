from datetime import datetime
from pydantic import BaseModel,ConfigDict
class AuditLogOut(BaseModel):
 model_config=ConfigDict(from_attributes=True)
 id:int;user_id:int|None;entity:str;entity_id:int;action:str;ip_address:str;delta_changes:dict;created_at:datetime
