"""Exercise cookie login -> upload -> verification -> official decision -> alert -> refund."""
import asyncio
import os
from datetime import date
from pathlib import Path
import httpx

API = os.getenv('FDR_API_URL', 'http://localhost:8000')
MAILHOG = os.getenv('MAILHOG_URL', 'http://mailhog:8025')


async def login(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    for attempt in range(45):
        try:
            response = await client.post('/api/v1/auth/login', json={'email': email, 'password': 'DemoPass123!'})
            break
        except httpx.ConnectError:
            if attempt == 44: raise
            await asyncio.sleep(1)
    response.raise_for_status()
    cookies = response.cookies
    return {'Cookie': '; '.join(f'{name}={value}' for name, value in cookies.items()),
            'X-CSRF-Token': cookies.get('csrf_token', '')}


async def main():
    scan = Path(__file__).parents[1] / 'sample_scans' / 'sample-sbi.png'
    if not scan.exists(): raise RuntimeError('Seed sample scan is missing; run scripts.seed first')
    async with httpx.AsyncClient(base_url=API, timeout=20) as client:
        institution = await login(client, 'institution1@example.test')
        fields = {'fdr_number':'00000036821805542', 'bank_name':'SBI', 'branch':'C.S.W.T. BSF CAMPUS', 'amount':'49000',
                  'issue_date':'2017-04-29', 'maturity_date':'2018-04-30',
                  'holder':'MR. SUBHASH KUMAR JAIN / MR. SUJEET KUMAR JAIN'}
        with scan.open('rb') as source:
            response = await client.post('/api/v1/fdrs', data=fields,
                files={'file':('sample-sbi.png', source, 'image/png')}, headers=institution)
        response.raise_for_status(); fdr_id = response.json()['fdr_id']
        print(f'uploaded FDR id={fdr_id}')

        report = {}
        for _ in range(150):
            await asyncio.sleep(1)
            report_response = await client.get(f'/api/v1/verification/{fdr_id}/report', headers=institution)
            report_response.raise_for_status(); report = report_response.json()
            if report.get('bank') or (report.get('ocr') and report['ocr'].get('confidence') == 0): break
        print(f"verification confidence={((report.get('ocr') or {}).get('confidence'))}; bank_found={bool((report.get('bank') or {}).get('found'))}; trust_badge={report.get('trust_badge')}")
        print(f"discrepancies={[(item.get('field'), item.get('declared_value'), item.get('extracted_value')) for item in report.get('discrepancies', [])]}")

        official = await login(client, 'officer@example.test')
        case = await client.get(f'/api/v1/fdrs/{fdr_id}', headers=official); case.raise_for_status()
        if case.json()['status'] == 'submitted':
            response = await client.patch(f'/api/v1/fdrs/{fdr_id}/status', json={'status':'under_scrutiny','remarks':'Demo review'}, headers=official); response.raise_for_status()
        case = await client.get(f'/api/v1/fdrs/{fdr_id}', headers=official); state = case.json()['status']
        if state == 'mismatch':
            response = await client.patch(f'/api/v1/fdrs/{fdr_id}/status', json={'status':'under_scrutiny','remarks':'Demo discrepancy reviewed'}, headers=official); response.raise_for_status()
        response = await client.patch(f'/api/v1/fdrs/{fdr_id}/status', json={'status':'verified','remarks':'Demo approval'}, headers=official); response.raise_for_status()
        print('AICTE Official approved FDR')
        open_discrepancies = await client.get('/api/v1/verification/discrepancies', params={'resolved':'false'}, headers=official)
        open_discrepancies.raise_for_status(); print(f"open seeded discrepancies={len(open_discrepancies.json())}")

        admin = await login(client, 'admin@example.test')
        response = await client.post(f'/api/v1/notifications/test?fdr_id={fdr_id}&stage=T-90', headers=admin); response.raise_for_status()
        await asyncio.sleep(3)
        chief = await login(client, 'chief@example.test')
        audit = await client.get('/api/v1/audit', params={'entity':'fdr','entity_id':fdr_id}, headers=chief)
        audit.raise_for_status(); print(f"audit events for flow={len(audit.json())}")
        dashboard = await client.get('/api/v1/dashboard/bureau', headers=chief)
        dashboard.raise_for_status(); summary = dashboard.json()
        print(f"dashboard banks={len(summary.get('value_by_bank', []))}; maturity_points={len(summary.get('maturity_timeline', []))}; statuses={len(summary.get('status_breakdown', []))}")
        institution = await login(client, 'institution1@example.test')
        refund = await client.post('/api/v1/refunds', json={'fdr_id':fdr_id,'reason':'Demo matured deposit release'}, headers=institution)
        refund.raise_for_status(); refund_id = refund.json()['id']
        response = await client.post(f'/api/v1/refunds/{refund_id}/decision', json={'decision':'approved','remarks':'Demo release approved'}, headers=chief); response.raise_for_status()
        try:
            messages=(await client.get(f'{MAILHOG}/api/v2/messages')).json()
            mail_count=messages.get('total',0)
        except Exception: mail_count='Mailhog API unavailable'
        print(f'alert stage=T-90; Mailhog messages={mail_count}; refund={refund_id} approved')


if __name__ == '__main__': asyncio.run(main())
