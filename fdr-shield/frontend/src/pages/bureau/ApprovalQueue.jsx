import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { client } from '../../api/client';
import { EmptyState, ErrorState, LoadingState, useToast } from '../../components/common/PageStates';

export default function ApprovalQueue(){
 const qc=useQueryClient(),toast=useToast();
 const q=useQuery({queryKey:['official-approvals'],queryFn:()=>client.get('/refunds',{params:{status:'pending'}}).then(r=>r.data),refetchInterval:5000});
 const decide=useMutation({mutationFn:({id,decision,remarks})=>client.post(`/refunds/${id}/decision`,{decision,remarks,idempotency_key:crypto.randomUUID()}),onSuccess:()=>{toast('Release decision recorded.');qc.invalidateQueries({queryKey:['official-approvals']});}});
 if(q.isLoading)return <LoadingState label="Loading release approvals"/>;
 if(q.isError)return <ErrorState error={q.error} onRetry={()=>q.refetch()} label="Cannot load approvals"/>;
 const rows=Array.isArray(q.data)?q.data:[];
 return <section><h1 className="text-3xl font-bold">Human approvals</h1><p className="mb-5 mt-1 text-slate-600">Review release/refund requests one case at a time. Bulk decisions are unavailable.</p>{!rows.length?<EmptyState title="No approvals waiting">Pending release requests will appear here.</EmptyState>:<div className="space-y-3">{rows.map(r=><ApprovalCard key={r.id} row={r} busy={decide.isPending} onDecision={(decision,remarks)=>decide.mutate({id:r.id,decision,remarks})}/>)}</div>}{decide.isError&&<ErrorState error={decide.error} label="Decision failed; review the current request and retry"/>}</section>;
}
function ApprovalCard({row,busy,onDecision}){const[remarks,setRemarks]=useState('');return <article className="rounded-xl border bg-white p-5"><h2 className="font-semibold">Release request #{row.id} · FDR #{row.fdr_id}</h2><p className="mt-1 text-sm text-slate-600">Reason: {row.remarks||'No reason supplied'}</p><label className="mt-3 block text-sm">Decision rationale<textarea value={remarks} onChange={e=>setRemarks(e.target.value)} className="mt-1 w-full rounded border p-2" required minLength={4}/></label><div className="mt-3 flex flex-wrap gap-2"><button disabled={busy||remarks.trim().length<4} onClick={()=>{if(window.confirm('Approve release and mark the FDR released?'))onDecision('approved',remarks)}} className="rounded-lg bg-emerald-800 px-4 py-2 text-white disabled:opacity-50">Approve release</button><button disabled={busy||remarks.trim().length<4} onClick={()=>{if(window.confirm('Reject this request? The FDR returns to verified.'))onDecision('rejected',remarks)}} className="rounded-lg border border-red-300 px-4 py-2 text-red-900 disabled:opacity-50">Reject request</button></div></article>}
