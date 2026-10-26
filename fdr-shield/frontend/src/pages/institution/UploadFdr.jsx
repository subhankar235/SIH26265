import { useState } from 'react';
import { useMutation,useQuery,useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { client } from '../../api/client';
import FdrUploadForm from '../../components/fdr/FdrUploadForm';
import TrustBadge from '../../components/common/TrustBadge';
import StatusPill from '../../components/common/StatusPill';
import { ErrorState,LoadingState,useToast } from '../../components/common/PageStates';

export default function UploadFdr(){
 const[fdrId,setFdrId]=useState(null),qc=useQueryClient(),toast=useToast();
 const upload=useMutation({mutationFn:form=>client.post('/fdrs',form).then(r=>r.data),onSuccess:data=>{setFdrId(data.fdr_id||data.id);toast('FDR submitted. Verification has started.');qc.invalidateQueries({queryKey:['fdrs']});}});
 const report=useQuery({queryKey:['report',fdrId],queryFn:()=>client.get(`/verification/${fdrId}/report`).then(r=>r.data),enabled:Boolean(fdrId),refetchInterval:q=>q.state.data?.bank||q.state.data?.ocr?.confidence===0?false:3000});
 return <section className="mx-auto max-w-3xl"><p className="text-sm font-semibold uppercase tracking-wide text-indigo-700">Institution portal</p><h1 className="mt-1 text-3xl font-bold">Submit an FDR</h1><p className="mb-6 mt-2 text-slate-600">Upload the receipt, review OCR suggestions, and confirm every field before submission.</p>{!fdrId?<FdrUploadForm onSubmit={form=>upload.mutate(form)} busy={upload.isPending} error={upload.error}/>:<div className="space-y-4 rounded-xl border bg-white p-6"><div><p className="text-sm text-slate-500">FDR reference</p><h2 className="text-xl font-semibold">#{fdrId}</h2></div>{report.isLoading?<LoadingState label="Waiting for verification report"/>:report.isError?<ErrorState error={report.error} onRetry={()=>report.refetch()} label="Could not load verification report"/>:<><div className="flex items-center gap-3"><StatusPill status={report.data?.trust_badge==='mismatch'?'mismatch':report.data?.trust_badge==='bank_verified'?'verified':'submitted'}/><TrustBadge badge={report.data?.trust_badge||'self_declared'}/></div>{report.data?.ocr?.confidence===0&&<p role="status" className="text-sm text-amber-800">OCR is temporarily unavailable. This FDR remains submitted for officer review.</p>}{report.data?.bank?.found&&<p className="text-sm text-slate-600">Demo bank gateway status: {report.data.bank.status}</p>}</>}<Link to="/institution/fdrs" className="inline-flex rounded-lg border px-4 py-2 text-sm font-semibold">View my FDRs</Link></div>}</section>;
}
