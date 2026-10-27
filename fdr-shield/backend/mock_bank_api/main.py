from fastapi import FastAPI
try:
    from mock_bank_api.store import lookup
    from mock_bank_api.models import VerifyRequest
except ModuleNotFoundError:
    from store import lookup
    from models import VerifyRequest

app=FastAPI(title='NidhiTrack Demo Bank Gateway')
@app.get('/banks')
def banks(): return ['sbi','pnb','hdfc']
def install(bank):
    @app.post(f'/{bank}/v1/fdr/verify')
    async def verify(body:VerifyRequest):
        row=lookup(bank,body.fdr_number)
        if not row: return {'found':False,'status':None,'amount':None,'maturity_date':None,'holder_name':None}
        return {'found':True,'status':row['status'],'amount':row['amount'],'maturity_date':row['maturity_date'],'holder_name':row['holder_name'],'lien_in_favor_of':'AICTE'}
    @app.get(f'/{bank}/v1/fdr/{{fdr_number}}/status')
    async def status(fdr_number:str):
        row=lookup(bank,fdr_number)
        return {'found':bool(row),'status':row['status'] if row else None}
for name in ('sbi','pnb','hdfc'): install(name)
