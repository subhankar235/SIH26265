"""Data-dependent ML gates, reproducible demos, and advisory-only fallbacks.

No training occurs here. Gate qualification is necessary but not sufficient: a real
trainer must be separately implemented, evaluated, and reviewed before promotion.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import platform
import random
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ExecutionState
from app.core.exceptions import InvalidStateTransition
from app.models.discrepancy import Discrepancy
from app.models.fdr import FDR
from app.models.workflow import WorkflowInstance
from app.models.ml import MLDemoSample, MLOperationsSnapshot, MLModelVersion, MLPrediction
from app.models.user import User
from app.services.audit_service import record

SEED = 202613
MODEL_PLANS: dict[str, dict] = {
    'institution_dagmm': {
        'model_name': 'DAGMM', 'feature_version': 'institution-fdr-v1',
        'target': 'Rank structured FDR feature vectors for unusual patterns; never authenticity or fraud classification.',
        'features': ['log_amount_inr', 'tenure_days', 'bank_one_hot{sbi,pnb,hdfc,other}', 'declaration_gap_count', 'filing_hour_utc', 'amount_missing', 'tenure_missing', 'filing_hour_missing'],
        'missing_policy': 'Missing numeric values are represented as null plus a missing indicator; no imputation is trained until validated.',
        'minimum_real_rows': 1000, 'clean_definition': 'Explicitly real FDR; complete amount/dates; no unresolved high-severity discrepancy.',
        'metrics': ['precision@k from blinded officer review', 'score calibration', 'coverage', 'vs Isolation Forest and robust z-score baseline'],
        'acceptance': {'precision_at_k_min': 0.80, 'reviewed_cases_min': 200, 'calibration_ece_max': 0.10,
                       'must_outperform_baseline': True},
        'fallback': 'deterministic_fdr_review_rules',
    },
    'official_deephit': {
        'model_name': 'DeepHit', 'feature_version': 'official-resolution-v1',
        'target': 'Time from workflow creation to first terminal resolution; event=completed_at, censor=still unresolved at extraction cutoff.',
        'features': ['initial_lifecycle_state', 'initial_node', 'amount_band', 'bank_category', 'maturity_days_at_start'],
        'missing_policy': 'Exclude rows missing start timestamp or event/censor status; censor duration at extraction cutoff; no post-start fields.',
        'minimum_resolved_rows': 500, 'minimum_censored_rows': 100, 'minimum_span_days': 90,
        'metrics': ['chronological holdout C-index', 'time-dependent AUC', 'calibration by time horizon', 'vs Cox/rule-based priority'],
        'acceptance': {'c_index_min': 0.65, 'time_auc_min': 0.65, 'calibration_slope_min': 0.8,
                       'calibration_slope_max': 1.2, 'must_outperform_baseline': True},
        'fallback': 'rule_based_deadline_priority',
    },
    'admin_bocpd': {
        'model_name': 'BOCPD', 'feature_version': 'admin-metrics-15m-v1',
        'target': 'Flag change points in operational metric series for investigation; never automatic incident rejection or action.',
        'features': ['failed_jobs', 'dead_letters', 'queue_age_seconds', 'workflow_duration_ms', 'notification_failure_rate_percent', 'stuck_cases'],
        'missing_policy': 'Persist UTC capture time and per-metric missingness; resample onto 15-minute UTC bins; forward-fill at most one bin, otherwise mark missing.',
        'minimum_samples': 1000, 'minimum_span_days': 30,
        'metrics': ['false-positive alerts per 30 days', 'median detection delay', 'vs deterministic threshold rules'],
        'acceptance': {'false_positive_rate_max': 0.05, 'detection_delay_minutes_max': 60,
                       'must_outperform_baseline': True},
        'fallback': 'deterministic_operations_thresholds',
    },
}
USE_CASES = set(MODEL_PLANS)


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)
    return sha256(raw.encode('utf-8')).hexdigest()


def _runtime_manifest() -> dict:
    from importlib.metadata import PackageNotFoundError, version
    versions={'python':platform.python_version(),'training':'disabled-no-trainer-installed'}
    for package in ('sqlalchemy','pydantic','fastapi'):
        try: versions[package]=version(package)
        except PackageNotFoundError: versions[package]='not-installed'
    return versions


async def _institution_gate(session: AsyncSession) -> dict:
    real = FDR.is_synthetic.is_(False)
    total = int(await session.scalar(select(func.count(FDR.id)).where(real)) or 0)
    complete_q = select(func.count(FDR.id)).where(real, FDR.amount.is_not(None), FDR.issue_date.is_not(None), FDR.maturity_date.is_not(None))
    complete = int(await session.scalar(complete_q) or 0)
    high_disc = select(Discrepancy.fdr_id).where(Discrepancy.resolved.is_(False), Discrepancy.severity == 'high')
    clean = int(await session.scalar(select(func.count(FDR.id)).where(
        real, FDR.amount.is_not(None), FDR.issue_date.is_not(None), FDR.maturity_date.is_not(None),
        FDR.id.not_in(high_disc))) or 0)
    first_workflow = select(WorkflowInstance.fdr_id.label('fdr_id'),
        func.min(WorkflowInstance.created_at).label('first_created_at')).group_by(WorkflowInstance.fdr_id).subquery()
    data = list((await session.execute(select(FDR.id,FDR.amount,FDR.issue_date,FDR.maturity_date,FDR.bank_name,
        FDR.ocr_data,first_workflow.c.first_created_at).outerjoin(first_workflow,first_workflow.c.fdr_id==FDR.id)
        .where(real).order_by(FDR.id))).all())
    features=[]
    for r in data:
        amount=float(r.amount) if r.amount is not None else None
        tenure=(r.maturity_date-r.issue_date).days if r.maturity_date and r.issue_date else None
        ocr=r.ocr_data or {}
        gap_count=sum(ocr.get(k) in (None,'') for k in ('fdr_number','bank_name','amount','maturity_date'))
        filed=r.first_created_at
        if filed and filed.tzinfo is None: filed=filed.replace(tzinfo=timezone.utc)
        bank=(r.bank_name or '').strip().lower()
        if bank not in {'sbi','pnb','hdfc'}: bank='other'
        features.append({'id':r.id,'log_amount_inr':round(math.log1p(amount),6) if amount is not None and amount>=0 else None,
            'tenure_days':tenure,'bank_one_hot':{name:bank==name for name in ('sbi','pnb','hdfc','other')},
            'declaration_gap_count':gap_count,'filing_hour_utc':filed.hour if filed else None,
            'amount_missing':amount is None,'tenure_missing':tenure is None,'filing_hour_missing':filed is None})
    enough = clean >= MODEL_PLANS['institution_dagmm']['minimum_real_rows']
    return {'use_case':'institution_dagmm','plan':MODEL_PLANS['institution_dagmm'],
        'real_rows':total,'clean_real_rows':clean,'complete_real_rows':complete,
        'unclassified_legacy_rows':int(await session.scalar(select(func.count(FDR.id)).where(FDR.is_synthetic.is_(None))) or 0),
        'synthetic_rows_excluded':int(await session.scalar(select(func.count(FDR.id)).where(FDR.is_synthetic.is_(True))) or 0)+
            int(await session.scalar(select(func.count(MLDemoSample.id)).where(MLDemoSample.use_case=='institution_dagmm',MLDemoSample.is_synthetic.is_(True))) or 0),
        'dataset_hash':_digest(features),'eligible_for_training_review':enough,
        'gate_status':'ELIGIBLE_FOR_TRAINING_REVIEW' if enough else 'BLOCKED_INSUFFICIENT_REAL_DATA',
        'active_behavior':MODEL_PLANS['institution_dagmm']['fallback']}


async def _official_gate(session: AsyncSession) -> dict:
    rows = list((await session.execute(select(WorkflowInstance.created_at, WorkflowInstance.completed_at)
        .join(FDR,FDR.id==WorkflowInstance.fdr_id)
        .where(FDR.is_synthetic.is_(False)).order_by(WorkflowInstance.created_at))).all())
    now = datetime.now(timezone.utc)
    normalized = []
    resolved = censored = 0
    for created, completed in rows:
        start = created.replace(tzinfo=timezone.utc) if created and created.tzinfo is None else created
        end = completed.replace(tzinfo=timezone.utc) if completed and completed.tzinfo is None else completed
        if not start: continue
        event = end is not None and end >= start
        resolved += int(event)
        censored += int(not event)
        normalized.append({'created_at':start.isoformat(),'duration_seconds':max(0,(end-start).total_seconds()) if event else max(0,(now-start).total_seconds()),
            'event_observed':event})
    span = ((datetime.fromisoformat(normalized[-1]['created_at']) - datetime.fromisoformat(normalized[0]['created_at'])).total_seconds()/86400) if len(normalized)>1 else 0
    plan = MODEL_PLANS['official_deephit']
    enough = resolved >= plan['minimum_resolved_rows'] and censored >= plan['minimum_censored_rows'] and span >= plan['minimum_span_days']
    unclassified=int(await session.scalar(select(func.count(WorkflowInstance.id)).join(FDR,FDR.id==WorkflowInstance.fdr_id).where(FDR.is_synthetic.is_(None))) or 0)
    synthetic=int(await session.scalar(select(func.count(WorkflowInstance.id)).join(FDR,FDR.id==WorkflowInstance.fdr_id).where(FDR.is_synthetic.is_(True))) or 0)
    return {'use_case':'official_deephit','plan':plan,'real_rows':len(normalized),'unclassified_legacy_rows':unclassified,'resolved_real_rows':resolved,
        'synthetic_rows_excluded':synthetic,
        'censored_real_rows':censored,'chronological_span_days':round(span,2),'dataset_hash':_digest(normalized),
        'eligible_for_training_review':enough,'gate_status':'ELIGIBLE_FOR_TRAINING_REVIEW' if enough else 'BLOCKED_INSUFFICIENT_REAL_DATA',
        'active_behavior':plan['fallback']}


async def _admin_gate(session: AsyncSession) -> dict:
    plan = MODEL_PLANS['admin_bocpd']
    rows = list((await session.scalars(select(MLOperationsSnapshot).where(
        MLOperationsSnapshot.is_synthetic.is_(False)).order_by(MLOperationsSnapshot.captured_at))).all())
    span = 0.0
    if len(rows)>1:
        first=rows[0].captured_at.replace(tzinfo=timezone.utc) if rows[0].captured_at.tzinfo is None else rows[0].captured_at
        last=rows[-1].captured_at.replace(tzinfo=timezone.utc) if rows[-1].captured_at.tzinfo is None else rows[-1].captured_at
        span=(last-first).total_seconds()/86400
    samples=[{'captured_at':r.captured_at,'metrics':r.metrics} for r in rows]
    unclassified=int(await session.scalar(select(func.count(MLOperationsSnapshot.id)).where(MLOperationsSnapshot.is_synthetic.is_(None))) or 0)
    enough=len(rows)>=plan['minimum_samples'] and span>=plan['minimum_span_days']
    return {'use_case':'admin_bocpd','plan':plan,'real_rows':len(rows),'span_days':round(span,2),
        'synthetic_rows_excluded':int(await session.scalar(select(func.count(MLOperationsSnapshot.id)).where(MLOperationsSnapshot.is_synthetic.is_(True))) or 0),
        'unclassified_legacy_rows':unclassified,
        'dataset_hash':_digest(samples),'eligible_for_training_review':enough,
        'gate_status':'ELIGIBLE_FOR_TRAINING_REVIEW' if enough else 'BLOCKED_INSUFFICIENT_REAL_DATA',
        'active_behavior':plan['fallback']}


async def assess_gates(session: AsyncSession) -> dict:
    gates=[await _institution_gate(session),await _official_gate(session),await _admin_gate(session)]
    return {'evaluated_at':datetime.now(timezone.utc).isoformat(),
        'training_started':False,'notice':'Gate eligibility is not training approval. No model is trained by this service.',
        'gates':gates}


async def register_gate_evaluation(session: AsyncSession, actor: User) -> dict:
    report=await assess_gates(session)
    for gate in report['gates']:
        version=f"gate0-{_digest(gate)[:16]}"
        previous=await session.scalar(select(MLModelVersion.id).where(
            MLModelVersion.use_case==gate['use_case'],MLModelVersion.version==version))
        if previous:
            continue
        row=MLModelVersion(use_case=gate['use_case'],version=version,model_name=gate['plan']['model_name'],
            status=gate['gate_status'],feature_version=gate['plan']['feature_version'],seed=SEED,
            dataset_hash=gate['dataset_hash'],training_rows=0,real_training_rows=gate['real_rows'],
            synthetic_training_rows=0,evaluation_metrics={'gate_counts':{k:v for k,v in gate.items() if k.endswith('_rows') or k.endswith('_days')},
                'training_performed':False},acceptance_criteria=gate['plan']['acceptance'],
            library_versions=_runtime_manifest(),fallback_name=gate['plan']['fallback'],is_synthetic=False)
        session.add(row);await session.flush()
        await record(session,actor.id,'ml_model_version',row.id,'ML_GATE_EVALUATED','',
            {'use_case':[None,row.use_case],'status':[None,row.status],
             'dataset_hash':[None,row.dataset_hash],'training_performed':[None,False]})
    return report


def _demo_features(use_case: str, rng: random.Random, i: int) -> dict:
    if use_case=='institution_dagmm':
        bank=rng.choice(['sbi','pnb','hdfc','other'])
        return {'log_amount_inr':round(rng.uniform(9,16),3),'tenure_days':rng.choice([365,730,1095,1825,3650]),
            'bank_one_hot':{name:bank==name for name in ('sbi','pnb','hdfc','other')},
            'declaration_gap_count':rng.choices([0,1,2,3],[.7,.18,.09,.03])[0],
            'filing_hour_utc':rng.randrange(24),'amount_missing':False,'tenure_missing':False,'filing_hour_missing':False,
            'example_pattern': 'review_candidate' if i%11==0 else 'typical'}
    if use_case=='official_deephit':
        return {'initial_lifecycle_state':rng.choice(['submitted','under_review','awaiting_institution']),
            'initial_node':rng.choice(['extract_document','validate_fields','route_case']),'amount_band':rng.choice(['small','medium','large']),
            'bank_category':rng.choice(['public','private','other']),'maturity_days_at_start':rng.randrange(1,2500),
            'demo_time_to_resolution_days':rng.randrange(1,181),'event_observed':rng.random()>.2}
    return {'failed_jobs':rng.randrange(0,8),'dead_letters':rng.choice([0,0,0,1]),
        'queue_age_seconds':rng.randrange(0,900),'workflow_duration_ms':rng.randrange(10,300000),
        'notification_failure_rate_percent':round(rng.random()*25,2),'stuck_cases':rng.randrange(0,4),
        'demo_change_point':i%25==0}


async def generate_synthetic_demo_data(session: AsyncSession, actor: User, count: int=200, seed: int=SEED) -> dict:
    if isinstance(count,bool) or not isinstance(count,int) or count<1 or count>5000:
        raise InvalidStateTransition('Synthetic sample count must be an integer between 1 and 5000.')
    if isinstance(seed,bool) or not isinstance(seed,int): raise InvalidStateTransition('Seed must be an integer.')
    rng=random.Random(seed);batch=str(uuid.uuid4());created=0
    for use_case,plan in MODEL_PLANS.items():
        rows=[MLDemoSample(batch_id=batch,use_case=use_case,feature_version=plan['feature_version'],
            sample_index=i,features=_demo_features(use_case,rng,i),is_synthetic=True) for i in range(count)]
        session.add_all(rows);created+=len(rows)
        demo_version=f'demo-synthetic-{batch[:8]}'
        session.add(MLModelVersion(use_case=use_case,version=demo_version,model_name=plan['model_name'],
            status='DEMO_ONLY_NOT_TRAINED',feature_version=plan['feature_version'],seed=seed,
            dataset_hash=_digest([row.features for row in rows]),training_rows=0,real_training_rows=0,
            synthetic_training_rows=count,evaluation_metrics={'training_performed':False,
                'warning':'Synthetic demonstration data; metrics are not real model evaluation.'},
            acceptance_criteria=plan['acceptance'],library_versions=_runtime_manifest(),
            fallback_name=plan['fallback'],is_synthetic=True))
    await session.flush()
    await record(session,actor.id,'ml_demo_batch',int(batch.replace('-','')[:12],16),'SYNTHETIC_DEMO_DATA_GENERATED','',
        {'batch_id':[None,batch],'rows_per_use_case':[None,count],'total_rows':[None,created],
         'is_synthetic':[None,True],'seed':[None,seed]})
    return {'batch_id':batch,'rows_per_use_case':count,'total_rows':created,'seed':seed,
        'is_synthetic':True,'training_performed':False,
        'warning':'DEMO ONLY — synthetic samples are excluded from Gate 0 and no model metrics are produced.'}


async def capture_operations_snapshot(session: AsyncSession, metrics: dict, *, is_synthetic: bool=False) -> MLOperationsSnapshot:
    row=MLOperationsSnapshot(captured_at=datetime.now(timezone.utc),metrics=metrics,is_synthetic=is_synthetic)
    session.add(row);await session.flush();return row


def institution_fallback(fdr: FDR) -> dict | None:
    """Fixed review-only rules; never authenticity, fraud, reject, or authorization."""
    reasons=[]
    if fdr.amount is None or fdr.amount<=0: reasons.append('amount_missing_or_nonpositive')
    if fdr.issue_date and fdr.maturity_date:
        tenure=(fdr.maturity_date-fdr.issue_date).days
        if tenure<30 or tenure>3650: reasons.append('unusual_tenure')
    extracted=fdr.ocr_data or {}
    if extracted and sum(extracted.get(key) in (None,'') for key in ('fdr_number','bank_name','amount','maturity_date'))>=2:
        reasons.append('multiple_extraction_gaps')
    if fdr.trust_badge=='mismatch': reasons.append('existing_discrepancy_requires_review')
    if not reasons: return None
    return {'score':None,'recommendation':'unusual pattern — review suggested',
        'predictor':'deterministic_fdr_review_rules','details':{'reason_codes':reasons,
            'authorization_effect':'none','is_synthetic':bool(fdr.is_synthetic)}}


async def institution_recommendations(session: AsyncSession, institution_id: int, fdr_id: int | None=None) -> dict:
    query=select(FDR).where(FDR.institution_id==institution_id)
    if fdr_id is not None: query=query.where(FDR.id==fdr_id)
    rows=list((await session.scalars(query.order_by(FDR.id.desc()).limit(200))).all())
    predictions=[]
    for fdr in rows:
        item=institution_fallback(fdr)
        if item:
            predictions.append({'fdr_id':fdr.id,'fdr_number':fdr.fdr_number,
                'recommendation':item['recommendation'],'predictor':item['predictor'],
                'details':item['details'],'is_synthetic':fdr.is_synthetic is True})
    return {'predictor':'deterministic_fdr_review_rules','training_performed':False,
        'notice':'Review suggestions only. No authenticity claim, rejection, or authorization action is made.',
        'recommendations':predictions}


def official_priority_fallback(workflow: WorkflowInstance, now: datetime | None=None) -> dict:
    now=now or datetime.now(timezone.utc)
    updated=workflow.updated_at.replace(tzinfo=timezone.utc) if workflow.updated_at and workflow.updated_at.tzinfo is None else workflow.updated_at
    hours=max(0,((now-updated).total_seconds()/3600)) if updated else 0
    if workflow.execution_state in {ExecutionState.FAILED.value,ExecutionState.BLOCKED.value}:
        priority='high';reason='workflow_failed_or_blocked'
    elif hours>=48 or workflow.execution_state=='waiting_human':
        priority='high';reason='long_wait_or_human_gate'
    elif hours>=24:
        priority='medium';reason='approaching_service_level_window'
    else:
        priority='normal';reason='within_service_level_window'
    return {'score':None,'recommendation':f'{priority.title()} review priority — inspect case timeline',
        'predictor':'rule_based_deadline_priority','details':{'priority':priority,'reason_code':reason,
            'hours_since_progress':round(hours,1),'authorization_effect':'none'}}


async def official_recommendations(session: AsyncSession, limit: int=200) -> dict:
    pairs=(await session.execute(select(WorkflowInstance,FDR).join(FDR,FDR.id==WorkflowInstance.fdr_id)
        .where(FDR.is_synthetic.is_not(None)).order_by(WorkflowInstance.updated_at).limit(limit))).all()
    output=[]
    for workflow,fdr in pairs:
        result=official_priority_fallback(workflow)
        output.append({'workflow_id':workflow.id,'fdr_id':fdr.id,'fdr_number':fdr.fdr_number,
            'recommendation':result['recommendation'],'predictor':result['predictor'],
            'details':result['details'],'is_synthetic':fdr.is_synthetic is True})
    return {'predictor':'rule_based_deadline_priority','training_performed':False,
        'notice':'Priority suggestions only. No authorization or workflow action is triggered.',
        'recommendations':output}


async def run_fallback_predictions(session: AsyncSession, actor: User, use_case: str='all', limit: int=100,
                                  idempotency_key: str | None=None) -> dict:
    if use_case not in USE_CASES|{'all'}: raise InvalidStateTransition('Unknown ML advisory use case.')
    if isinstance(limit,bool) or not isinstance(limit,int) or limit<1 or limit>500:
        raise InvalidStateTransition('Prediction limit must be an integer between 1 and 500.')
    idempotency_key=idempotency_key or str(uuid.uuid4())
    if not isinstance(idempotency_key,str) or len(idempotency_key)<8 or len(idempotency_key)>255:
        raise InvalidStateTransition('A valid prediction idempotency key is required.')
    def dedupe(use_case_key,entity_type,entity_id):
        return sha256(f'{idempotency_key}|{use_case_key}|{entity_type}|{entity_id}'.encode()).hexdigest()
    selected=USE_CASES if use_case=='all' else {use_case};created=[]
    if 'institution_dagmm' in selected:
        rows=list((await session.scalars(select(FDR).where(FDR.is_synthetic.is_(False)).order_by(FDR.id.desc()).limit(limit))).all())
        for fdr in rows:
            result=institution_fallback(fdr)
            if result:
                key=dedupe('institution_dagmm','fdr',fdr.id)
                if await session.scalar(select(MLPrediction.id).where(MLPrediction.dedupe_key==key)): continue
                pred=MLPrediction(use_case='institution_dagmm',entity_type='fdr',entity_id=fdr.id,
                    predictor=result['predictor'],score=None,recommendation=result['recommendation'],details=result['details'],is_synthetic=False,dedupe_key=key)
                session.add(pred);created.append(pred)
    if 'official_deephit' in selected:
        pairs=(await session.execute(select(WorkflowInstance,FDR).join(FDR,FDR.id==WorkflowInstance.fdr_id)
            .where(FDR.is_synthetic.is_(False)).order_by(WorkflowInstance.updated_at).limit(limit))).all()
        for workflow,fdr in pairs:
            result=official_priority_fallback(workflow)
            key=dedupe('official_deephit','workflow',workflow.id)
            if await session.scalar(select(MLPrediction.id).where(MLPrediction.dedupe_key==key)): continue
            pred=MLPrediction(use_case='official_deephit',entity_type='workflow',entity_id=workflow.id,
                predictor=result['predictor'],score=None,recommendation=result['recommendation'],
                details={**result['details'],'fdr_id':fdr.id},is_synthetic=False,dedupe_key=key)
            session.add(pred);created.append(pred)
    if 'admin_bocpd' in selected:
        from app.services.admin_ops_service import generate_health_report
        report=await generate_health_report(session)
        if report['breaches']:
            for breach in report['breaches']:
                key=dedupe('admin_bocpd','system',breach['rule'])
                if await session.scalar(select(MLPrediction.id).where(MLPrediction.dedupe_key==key)): continue
                pred=MLPrediction(use_case='admin_bocpd',entity_type='system',entity_id=None,
                    predictor='deterministic_operations_thresholds',score=None,
                    recommendation='Threshold breach — review suggested',details={'rule':breach['rule'],
                        'severity':breach['severity'],'message':breach['message'],'authorization_effect':'none'},is_synthetic=False,dedupe_key=key)
                session.add(pred);created.append(pred)
    await session.flush()
    if created:
        await record(session,actor.id,'ml_prediction_batch',created[-1].id,'ADVISORY_FALLBACKS_RUN','',
            {'use_case':[None,use_case],'count':[0,len(created)],'authorization_effect':[None,'none']})
    return {'count':len(created),'predictions':[{'id':p.id,'use_case':p.use_case,'entity_type':p.entity_type,
        'entity_id':p.entity_id,'predictor':p.predictor,'recommendation':p.recommendation,
        'details':p.details,'is_synthetic':p.is_synthetic} for p in created],
        'duplicate':len(created)==0,'notice':'Fallback recommendations only. They do not alter authorization or case state.'}


async def list_registry(session: AsyncSession, limit: int=200) -> list[dict]:
    rows=list((await session.scalars(select(MLModelVersion).order_by(MLModelVersion.created_at.desc()).limit(limit))).all())
    return [{'id':r.id,'use_case':r.use_case,'version':r.version,'model_name':r.model_name,'status':r.status,
        'feature_version':r.feature_version,'seed':r.seed,'dataset_hash':r.dataset_hash,
        'training_rows':r.training_rows,'real_training_rows':r.real_training_rows,
        'synthetic_training_rows':r.synthetic_training_rows,'evaluation_metrics':r.evaluation_metrics,
        'acceptance_criteria':r.acceptance_criteria,'library_versions':r.library_versions,'fallback_name':r.fallback_name,
        'is_synthetic':r.is_synthetic,'created_at':r.created_at.isoformat()} for r in rows]


async def list_predictions(session: AsyncSession, is_synthetic: bool | None=None, limit: int=200) -> list[dict]:
    query=select(MLPrediction).order_by(MLPrediction.created_at.desc()).limit(limit)
    if is_synthetic is not None: query=query.where(MLPrediction.is_synthetic.is_(is_synthetic))
    rows=list((await session.scalars(query)).all())
    return [{'id':r.id,'use_case':r.use_case,'entity_type':r.entity_type,'entity_id':r.entity_id,
        'predictor':r.predictor,'score':r.score,'recommendation':r.recommendation,
        'details':r.details,'is_synthetic':r.is_synthetic,'created_at':r.created_at.isoformat()} for r in rows]


async def list_demo_samples(session: AsyncSession, limit: int=100) -> list[dict]:
    rows=list((await session.scalars(select(MLDemoSample).where(MLDemoSample.is_synthetic.is_(True))
        .order_by(MLDemoSample.id.desc()).limit(limit))).all())
    return [{'id':r.id,'batch_id':r.batch_id,'use_case':r.use_case,'feature_version':r.feature_version,
        'sample_index':r.sample_index,'features':r.features,'is_synthetic':True,
        'created_at':r.created_at.isoformat()} for r in rows]
