from pydantic import BaseModel, ConfigDict
class InstitutionCreate(BaseModel): aicte_id:str; name:str; state:str; head_name:str; contact_email:str; contact_phone:str
class InstitutionOut(BaseModel):
 model_config=ConfigDict(from_attributes=True)
 id:int; aicte_id:str; name:str; state:str; head_name:str; contact_email:str; contact_phone:str; telegram_chat_id:str|None=None; fdr_count:int=0; total_value:float=0
