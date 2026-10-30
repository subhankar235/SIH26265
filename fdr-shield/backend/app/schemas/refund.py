from pydantic import BaseModel, Field
class RefundCreate(BaseModel): fdr_id:int; reason:str
class RefundDecision(BaseModel):
 decision:str
 remarks:str=Field(min_length=1, max_length=2000)
 idempotency_key:str|None=Field(default=None,min_length=8,max_length=255)
class RefundOut(BaseModel): id:int; fdr_id:int; requested_by:int; status:str; reviewed_by:int|None=None; remarks:str|None=None
