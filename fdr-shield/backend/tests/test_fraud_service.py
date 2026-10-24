import asyncio
from app.services.fraud_service import compare_records
from app.schemas.verification import OcrResult,BankVerifyResponse

def test_compare_records_flags_critical_mismatches():
    declared={'fdr_number':'SBI100001','amount':1000000,'maturity_date':'2027-03-31','bank_name':'SBI','holder':'ABC Institute'}
    ocr=OcrResult(fdr_number='SBI100001',amount=1000000,maturity_date='2027-03-31',bank_name='SBI')
    bank=BankVerifyResponse(found=True,status='ACTIVE',amount=900000,maturity_date='2027-03-31',holder='ABC Institute')
    out=asyncio.run(compare_records(declared,ocr,bank))
    assert any(x.field=='amount' and x.severity=='high' for x in out)

def test_compare_records_treats_integer_and_decimal_amounts_as_equal():
    declared={'fdr_number':'SBI100001','amount':'500000','maturity_date':'2027-03-31','bank_name':'SBI','holder':'ABC Institute'}
    ocr=OcrResult(fdr_number='SBI100001',amount='500000.00',maturity_date='2027-03-31',bank_name='SBI',holder_name='ABC Institute')
    bank=BankVerifyResponse(found=True,status='ACTIVE',amount='500000.0',maturity_date='2027-03-31',holder='ABC Institute')
    assert asyncio.run(compare_records(declared,ocr,bank))==[]
