"""Idempotently seed demo users, institutions, FDRs and mock bank fixtures."""
import asyncio
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.core.enums import FDRStatus, Role, TrustBadge
from app.core.security import hash_password
from app.models import FDR, Institution, User
from app.models.discrepancy import Discrepancy

PASSWORD = 'DemoPass123!'
NAMES = [
    ('ABC Institute of Technology', 'Delhi'),
    ('XYZ College of Engineering', 'Punjab'),
    ('PQR Polytechnic', 'Maharashtra'),
    ('National Institute of Design', 'Gujarat'),
    ('Eastern Technical University', 'West Bengal'),
]

async def seed():
    from app.core.config import get_settings
    if get_settings().app_env.lower() not in {'dev', 'development', 'test'}:
        raise RuntimeError('Demo seed data is disabled outside development/test environments.')
    await init_db()
    bank_rows = {
        'sbi': [
            {'fdr_number':'SBI100001','holder_name':'ABC Institute of Technology','amount':1000000,'maturity_date':'2027-03-31','status':'ACTIVE'},
            {'fdr_number':'SBI100099','holder_name':'ABC Institute of Technology','amount':850000,'maturity_date':'2027-03-31','status':'ACTIVE'},
        ],
        'pnb': [{'fdr_number':'PNB200001','holder_name':'XYZ College of Engineering','amount':500000,'maturity_date':'2026-12-15','status':'ACTIVE'}],
        'hdfc': [{'fdr_number':'HDFC300001','holder_name':'PQR Polytechnic','amount':750000,'maturity_date':'2026-11-20','status':'ACTIVE'}],
    }
    async with SessionLocal() as session:
        institutions = []
        for i, (name, state) in enumerate(NAMES, 1):
            inst = await session.scalar(select(Institution).where(Institution.aicte_id == f'AICTE-DEMO-{i:03}'))
            if not inst:
                inst = Institution(aicte_id=f'AICTE-DEMO-{i:03}', name=name, state=state,
                    head_name=f'Demo Principal {i}', contact_email=f'institution{i}@example.test', contact_phone=f'900000000{i}')
                session.add(inst); await session.flush()
            institutions.append(inst)
            email = f'institution{i}@example.test'
            if not await session.scalar(select(User.id).where(User.email == email)):
                session.add(User(email=email, password_hash=hash_password(PASSWORD), role=Role.INSTITUTION.value,
                                 institution_id=inst.id, is_active=True))

        staff = [('officer@example.test', Role.AICTE_OFFICIAL), ('chief@example.test', Role.AICTE_OFFICIAL), ('admin@example.test', Role.ADMIN)]
        for email, role in staff:
            existing_user = await session.scalar(select(User).where(User.email == email))
            if not existing_user:
                session.add(User(email=email, password_hash=hash_password(PASSWORD), role=role.value, is_active=True))
            else:
                existing_user.role = role.value

        today = date.today()
        offsets = [-20, 0, 30, 90, 120, 30, 90, 180, -5, 60, 120, 30, 90, 180, 365]
        banks = ['sbi', 'pnb', 'hdfc']
        for i in range(15):
            inst = institutions[i % len(institutions)]
            bank = banks[i % len(banks)]
            prefix = {'sbi': 'SBI', 'pnb': 'PNB', 'hdfc': 'HDFC'}[bank]
            number = f'{prefix}{700000 + i:06}'
            amount = Decimal(500000 + i * 50000)
            maturity = today + timedelta(days=offsets[i])
            mismatch = i in {2, 7, 12}
            bank_amount = amount + Decimal('50000') if mismatch else amount
            status = FDRStatus.EXPIRED.value if offsets[i] < 0 else (FDRStatus.MISMATCH.value if mismatch else (FDRStatus.VERIFIED.value if i % 4 == 1 else FDRStatus.SUBMITTED.value))
            badge = TrustBadge.MISMATCH.value if mismatch else (TrustBadge.BANK_VERIFIED.value if status == FDRStatus.VERIFIED.value else TrustBadge.SELF_DECLARED.value)
            fdr = await session.scalar(select(FDR).where(FDR.fdr_number == number))
            declared = {'fdr_number': number, 'bank_name': bank.upper(), 'branch': 'Main Branch', 'amount': float(amount),
                        'issue_date': (today - timedelta(days=365)).isoformat(), 'maturity_date': maturity.isoformat(), 'holder': inst.name}
            if not fdr:
                fdr = FDR(institution_id=inst.id, fdr_number=number, bank_name=bank.upper(), branch='Main Branch', amount=amount,
                    issue_date=today-timedelta(days=365), maturity_date=maturity, status=status, trust_badge=badge, declared_data=declared,
                    is_synthetic=True)
                session.add(fdr)
            fdr.is_synthetic = True
            fdr.status=status; fdr.trust_badge=badge
            fdr.ocr_data={'fdr_number': number, 'bank_name': bank.upper(), 'holder_name': inst.name, 'amount': str(amount),
                'issue_date': (today-timedelta(days=365)).isoformat(), 'maturity_date': maturity.isoformat(), 'confidence': 1.0}
            fdr.bank_data={'found': True, 'status': 'ACTIVE', 'amount': str(bank_amount), 'maturity_date': maturity.isoformat(), 'holder': inst.name}
            if mismatch and not await session.scalar(select(Discrepancy.id).where(Discrepancy.fdr_id == fdr.id, Discrepancy.field == 'amount')):
                await session.flush()
                session.add(Discrepancy(fdr_id=fdr.id, field='amount', declared_value=str(amount), extracted_value=str(bank_amount), source='bank_api', severity='high', resolved=False))
            bank_rows[bank].append({'fdr_number': number, 'holder_name': inst.name, 'amount': float(bank_amount),
                'maturity_date': maturity.isoformat(), 'status': 'ACTIVE'})

        await session.commit()

    fixture = Path(__file__).parents[1] / 'mock_bank_api' / 'data' / 'seed_fdrs.json'
    # These exact demo records correspond to the printed genuine reference samples.
    bank_rows['sbi'].append({'fdr_number':'00000036821805542','holder_name':'MR. SUBHASH KUMAR JAIN / MR. SUJEET KUMAR JAIN',
        'amount':49000,'issue_date':'2017-04-29','maturity_date':'2018-04-30','status':'ACTIVE'})
    bank_rows['hdfc'].append({'fdr_number':'50300277148239','holder_name':'MS RAJWINDER KAUR',
        'amount':450000,'issue_date':'2022-09-01','maturity_date':'2023-09-03','status':'ACTIVE'})
    bank_rows['pnb'].append({'fdr_number':'1558000101602751','holder_name':'KARAMBIR',
        'amount':800000,'issue_date':'2024-09-14','maturity_date':'2026-09-14','status':'ACTIVE'})
    bank_rows['sbi'].append({'fdr_number':'SBI-DEMO-MISMATCH','holder_name':'ABC Institute of Technology',
        'amount':99000,'issue_date':'2017-04-29','maturity_date':'2018-04-30','status':'ACTIVE'})
    fixture.write_text(json.dumps(bank_rows, indent=2) + '\n', encoding='utf-8')
    scan_dir = Path(__file__).parents[1] / 'sample_scans'; scan_dir.mkdir(exist_ok=True)
    reference_root = Path(__file__).parents[1] / 'reference_formats'
    for bank in ('sbi', 'hdfc', 'pnb'):
        source = reference_root / bank / f'{bank}_reference.png'
        if not source.is_file(): raise RuntimeError(f'Missing genuine demo scan: {source}')
        (scan_dir / f'sample-{bank}.png').write_bytes(source.read_bytes())

    print('FDR-Shield demo credentials (password for all: DemoPass123!):')
    print('  officer@example.test and chief@example.test (AICTE Official), admin@example.test')
    for i in range(1, 6): print(f'  institution{i}@example.test')

if __name__ == '__main__': asyncio.run(seed())
