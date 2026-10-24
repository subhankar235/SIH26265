from datetime import date
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field
class FDRCreate(BaseModel):
 fdr_number:str=Field(min_length=3,max_length=50); bank_name:str; branch:str=''; amount:Decimal=Field(gt=0); issue_date:date; maturity_date:date; holder:str=''
class FDROut(BaseModel):
 model_config=ConfigDict(from_attributes=True)
 id:int; institution_id:int; fdr_number:str; bank_name:str; branch:str; amount:Decimal; issue_date:date; maturity_date:date; status:str; trust_badge:str; declared_data:dict; ocr_data:dict|None=None; bank_data:dict|None=None; days_to_maturity:int|None=None
class FDRStatusUpdate(BaseModel): status:str; remarks:str|None=None
class RenewalRequest(BaseModel): new_fdr_number:str; new_maturity_date:date; amount:Decimal
