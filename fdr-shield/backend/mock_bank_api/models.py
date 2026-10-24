from pydantic import BaseModel
from datetime import date
from decimal import Decimal
class VerifyRequest(BaseModel): fdr_number:str; holder_name:str=''
class VerifyResponse(BaseModel): found:bool; status:str|None=None; amount:Decimal|None=None; maturity_date:date|None=None; holder_name:str|None=None; lien_in_favor_of:str|None=None
