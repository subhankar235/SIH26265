from pydantic import BaseModel
class RefundCreate(BaseModel): fdr_id:int; reason:str
class RefundDecision(BaseModel): decision:str; remarks:str=''
class RefundOut(BaseModel): id:int; fdr_id:int; requested_by:int; status:str; reviewed_by:int|None=None; remarks:str|None=None
