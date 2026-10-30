import { useState } from 'react';
import { useQuery,useMutation,useQueryClient } from '@tanstack/react-query';
import { useParams,useNavigate } from 'react-router-dom';
import { client } from '../../api/client';
import SplitViewer from '../../components/fdr/SplitViewer';
import DiscrepancyList from '../../components/fdr/DiscrepancyList';
import TrustBadge from '../../components/common/TrustBadge';
import StatusPill from '../../components/common/StatusPill';
import ConfirmDialog from '../../components/common/ConfirmDialog';
import { ErrorState,LoadingState,DataOriginBadge,useToast } from '../../components/common/PageStates';

export default function ScrutinySplitView(){
 const{id}=useParams(),nav=useNavigate(),qc=useQueryClient(),toast=useToast();const[decisionIntent,setDecisionIntent]=useState(''),[rationale,setRationale]=useState('');
 const f=useQuery({queryKey:['fdr',id],queryFn:()=>client.get(`/fdrs/${id}`).then(r=>r.data)});
 const report=useQuery({queryKey:['report',id],queryFn:()=>client.get(`/verification/${id}/report`).then(r=>r.data),refetchInterval:5000});
 const doc=useQuery({
  queryKey:['fdr-doc',id],
  queryFn:()=>client.get(`/fdrs/${id}/presigned-url`).then(r=>r.data.url),
  retry:(failureCount,error)=>error.response?.status!==404&&failureCount<2,
  staleTime:4*60*1000,
  refetchOnWindowFocus:true,
  refetchInterval:query=>query.state.error?.response?.status===404?10000:false,
 });
 const retryVerification=useMutation({
  mutationFn:()=>client.post(`/verification/${id}/run`,null,{
   params:{reason:'Official requested OCR and bank gateway retry from scrutiny review.'},
   headers:{'Idempotency-Key':`scrutiny-retry-${id}-${Date.now()}`},
  }).then(r=>r.data),
  onSuccess:data=>{toast(data.resumed?'Local verification resumed. Evidence will refresh automatically.':'Verification retry queued. This page will refresh the evidence automatically.');qc.invalidateQueries({queryKey:['report',id]});qc.invalidateQueries({queryKey:['fdr',id]});},
 });
 const decision=useMutation({mutationFn:async({status,remarks})=>{if(f.data.status==='submitted')await client.patch(`/fdrs/${id}/status`,{status:'under_scrutiny',remarks:'Official review started'});return client.patch(`/fdrs/${id}/status`,{status,remarks})},onSuccess:()=>{toast('Scrutiny decision saved and audited.');qc.invalidateQueries({queryKey:['fdr',id]});nav('/official/queue')}});
 const resolve=useMutation({mutationFn:discrepancyId=>client.post(`/verification/discrepancies/${discrepancyId}/resolve`,null,{params:{remarks:'Reviewed in split viewer'}}),onSuccess:()=>{toast('Discrepancy marked reviewed.');qc.invalidateQueries({queryKey:['report',id]})}});
 if(f.isLoading)return <LoadingState label="Loading scrutiny case"/>;if(f.error)return <ErrorState error={f.error} onRetry={()=>f.refetch()} label="Could not load scrutiny case"/>;
 const selected=decisionIntent;
 const workflowActive=['not_started','running','retrying'].includes(f.data.execution_state);
 const canResumeInline=Boolean(report.data?.processing?.local_inline_enabled)&&workflowActive;
 const scanDisabled=retryVerification.isPending||!doc.data||doc.isLoading||(workflowActive&&!canResumeInline);
 const scanLabel=retryVerification.isPending?'Scanning document…'
  :workflowActive&&!canResumeInline?'Verification is in progress'
  :report.data?.processing?.extraction_status==='succeeded'?'Scan again':'Scan document & check bank';
 return <section className="mx-auto max-w-[1500px] pb-24"><button className="mb-4 rounded text-sm text-indigo-800 focus-visible:outline focus-visible:outline-2" onClick={()=>nav('/official/queue')}>← Back to queue</button><header className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm text-slate-600">Official review</p><h1 className="text-2xl font-bold">{f.data.fdr_number}</h1><p className="text-sm text-slate-500">{f.data.bank_name} · {f.data.branch}</p>{f.data.is_synthetic&&<DataOriginBadge isSynthetic/>}</div><div className="flex items-center gap-2"><StatusPill status={f.data.lifecycle_state||f.data.status}/><TrustBadge badge={f.data.trust_badge}/></div></header>
 <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-indigo-200 bg-indigo-50 p-4">
  <div><h2 className="font-semibold text-indigo-950">Document scan and bank check</h2>
   <p className="mt-1 text-sm text-indigo-900">Run OCR and the configured demo-bank check using the scan on file. Results remain visible below and are saved with the workflow evidence.</p>
   {report.data?.processing?.extraction_completed_at&&<p className="mt-1 text-xs text-indigo-800">Last OCR completed {new Date(report.data.processing.extraction_completed_at).toLocaleString()}</p>}
   {!doc.data&&doc.error?.response?.status===404&&<p className="mt-1 text-xs text-amber-900">Upload a scan before running OCR.</p>}
   {workflowActive&&!canResumeInline&&<p className="mt-1 text-xs text-indigo-800">A verification workflow is already running. Its results will refresh automatically.</p>}
  </div>
  <button type="button" disabled={scanDisabled} onClick={()=>retryVerification.mutate()} className="rounded-lg bg-indigo-950 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50">{canResumeInline&&!retryVerification.isPending?'Resume local scan':scanLabel}</button>
  {retryVerification.isError&&<p role="alert" className="w-full text-sm text-red-800">Could not start document scan: {retryVerification.error.response?.data?.detail||retryVerification.error.message}</p>}
 </div>
 {doc.isError&&!doc.data?<div role="alert" className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-5 text-amber-950"><p className="font-semibold">{doc.error.response?.status===404?'No scan is attached to this FDR.':'Unable to load the document preview.'}</p><p className="mt-1 text-sm">{doc.error.response?.status===404?'The OCR/evidence results may still be available, but there is no stored scan to display. Ask the institution to upload the receipt. This page checks again automatically every 10 seconds.':'The preview link could not be retrieved. Retry, or check storage service availability.'}</p><button type="button" disabled={doc.isFetching} onClick={()=>doc.refetch()} className="mt-3 rounded-lg border border-amber-700 bg-white px-3 py-2 text-sm font-semibold disabled:opacity-60">{doc.isFetching?'Checking…':'Check document again'}</button></div>:doc.isError?<><p role="status" className="mb-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">Could not refresh the preview link. Showing the previously issued link, which may have expired. <button type="button" onClick={()=>doc.refetch()} className="font-semibold underline">Refresh preview</button></p><SplitViewer fileUrl={doc.data} fdr={f.data} report={report.data}/></>:<SplitViewer fileUrl={doc.data} fdr={f.data} report={report.data}/>}
<<<<<<< HEAD
  {report.data?.review_assessment&&<aside className="mt-5 rounded-xl border border-indigo-200 bg-indigo-50 p-4"><h2 className="font-semibold text-indigo-950">Advisory review signal</h2><p className="mt-1 text-sm text-indigo-900">{report.data.review_assessment.summary}</p><p className="mt-2 text-xs text-indigo-800">Advisory only. Review the source values and recorded findings before taking an official action.</p></aside>}
  <div className="mt-5"><h2 className="mb-2 font-semibold">Evidence and discrepancy observations</h2>{report.isLoading?<LoadingState label="Loading evidence"/>:report.isError?<ErrorState error={report.error} onRetry={()=>report.refetch()}/>:<DiscrepancyList items={report.data?.discrepancies||[]} onResolve={discrepancyId=>resolve.mutate(discrepancyId)}/>}</div>{resolve.isError&&<ErrorState error={resolve.error} label="Could not resolve observation"/>}{decision.error&&<ErrorState error={decision.error} label="Decision rejected; current case state may have changed"/>}<div className="fixed inset-x-0 bottom-0 z-20 flex flex-wrap items-center justify-between gap-3 border-t bg-white/95 px-4 py-3 shadow-lg backdrop-blur sm:px-6"><label className="min-w-48 flex-1 text-sm">Decision rationale<input value={rationale} onChange={e=>setRationale(e.target.value)} minLength={4} className="mt-1 w-full rounded border p-2" placeholder="Required for audit"/></label><div className="flex gap-2"><button disabled={decision.isPending||rationale.trim().length<4} onClick={()=>setDecisionIntent('mismatch')} className="rounded-lg border border-red-300 px-4 py-2 text-sm font-semibold text-red-800">Request correction</button><button disabled={decision.isPending||rationale.trim().length<4} onClick={()=>setDecisionIntent('verified')} className="rounded-lg bg-indigo-900 px-5 py-2 text-sm font-semibold text-white">Approve</button></div></div><ConfirmDialog open={Boolean(selected)} title={selected==='verified'?'Approve FDR':'Request institution correction'} message={selected==='verified'?`Record approval for ${f.data.fdr_number}. This updates case lifecycle, authorization, audit history, and queues downstream effects.`:`Request corrections for ${f.data.fdr_number}. The institution will be asked to upload a corrected document.`} onCancel={()=>setDecisionIntent('')} onConfirm={()=>{decision.mutate({status:selected,remarks:rationale.trim()});setDecisionIntent('')}}/></section>;
=======
 <div className="mt-5"><h2 className="mb-2 font-semibold">Evidence and discrepancy observations</h2>{report.isLoading?<LoadingState label="Loading evidence"/>:report.isError?<ErrorState error={report.error} onRetry={()=>report.refetch()}/>:<DiscrepancyList items={report.data?.discrepancies||[]} onResolve={discrepancyId=>resolve.mutate(discrepancyId)}/>}</div>{resolve.isError&&<ErrorState error={resolve.error} label="Could not resolve observation"/>}{decision.error&&<ErrorState error={decision.error} label="Decision rejected; current case state may have changed"/>}<div className="fixed inset-x-0 bottom-0 z-20 flex flex-wrap items-center justify-between gap-3 border-t bg-white/95 px-4 py-3 shadow-lg backdrop-blur sm:px-6"><label className="min-w-48 flex-1 text-sm">Decision rationale<input value={rationale} onChange={e=>setRationale(e.target.value)} minLength={4} className="mt-1 w-full rounded border p-2" placeholder="Required for audit"/></label><div className="flex gap-2"><button disabled={decision.isPending||rationale.trim().length<4} onClick={()=>setDecisionIntent('mismatch')} className="rounded-lg border border-red-300 px-4 py-2 text-sm font-semibold text-red-800">Request correction</button><button disabled={decision.isPending||rationale.trim().length<4} onClick={()=>setDecisionIntent('verified')} className="rounded-lg bg-indigo-900 px-5 py-2 text-sm font-semibold text-white">Approve</button></div></div><ConfirmDialog open={Boolean(selected)} title={selected==='verified'?'Approve FDR':'Request institution correction'} message={selected==='verified'?`Record approval for ${f.data.fdr_number}. This updates case lifecycle, authorization, audit history, and queues downstream effects.`:`Request corrections for ${f.data.fdr_number}. The institution will be asked to upload a corrected document.`} onCancel={()=>setDecisionIntent('')} onConfirm={()=>{decision.mutate({status:selected,remarks:rationale.trim()});setDecisionIntent('')}}/></section>;
>>>>>>> a27ee110f6ba3d79cb2eb0cff239996b7f97ea26
}
