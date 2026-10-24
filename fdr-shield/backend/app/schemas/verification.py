from datetime import date
from decimal import Decimal
from pydantic import BaseModel
class OcrResult(BaseModel): fdr_number:str|None=None; bank_name:str|None=None; holder_name:str|None=None; amount:Decimal|None=None; issue_date:date|None=None; maturity_date:date|None=None; confidence:float=0
class BankVerifyResponse(BaseModel): found:bool=False; status:str|None=None; amount:Decimal|None=None; maturity_date:date|None=None; holder:str|None=None
class DiscrepancyOut(BaseModel): field:str; declared_value:str|None=None; extracted_value:str|None=None; source:str; severity:str; resolved:bool=False
class VerificationReport(BaseModel): ocr:OcrResult|None=None; bank:BankVerifyResponse|None=None; discrepancies:list[DiscrepancyOut]=[]; trust_badge:str
