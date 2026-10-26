import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { client } from '../../api/client';
import { useAuthStore } from '../../store/authStore';
import StatusPill from '../../components/common/StatusPill';
import RefundDecisionPanel from '../../components/refund/RefundDecisionPanel';
import { EmptyState,ErrorState,LoadingState,useToast } from '../../components/common/PageStates';

export default function BureauRefunds() {
  const queryClient=useQueryClient(),user=useAuthStore(s=>s.user),toast=useToast();
  const query=useQuery({queryKey:['bureau-refunds'],queryFn:()=>client.get('/refunds').then(r=>r.data),staleTime:15000,refetchInterval:10000});
  const decision=useMutation({mutationFn:({id,decision:value,remarks})=>client.post(`/refunds/${id}/decision`,{decision:value,remarks,idempotency_key:crypto.randomUUID()}),onSuccess:()=>{toast('Release decision recorded.');queryClient.invalidateQueries({queryKey:['bureau-refunds']});}});
  if(query.isLoading)return <LoadingState label="Loading release approvals"/>;
  if(query.error)return <ErrorState error={query.error} onRetry={()=>query.refetch()} label="Refund requests could not be loaded"/>;
  const rows=Array.isArray(query.data)?query.data:[];
  return <section><p className="text-sm font-semibold uppercase tracking-wide text-indigo-700">Bureau workspace</p><h1 className="mb-2 mt-1 text-3xl font-bold">Refund decisions</h1><p className="mb-6 text-slate-600">Review release requests for matured, verified deposits.</p>{!rows.length?<EmptyState title="No refund requests yet">Institution release requests will appear here for review.</EmptyState>:<div className="space-y-4">{rows.map(item=><article key={item.id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-600">Request #{item.id}</p><h2 className="mt-1 font-semibold">FDR #{item.fdr_id}</h2><p className="mt-1 text-sm text-slate-700">{item.remarks||'No request remarks provided'}</p></div><StatusPill status={item.status}/></div>{item.status==='pending'&&user?.role==='aicte_official'&&<RefundDecisionPanel refund={item} busy={decision.isPending} onDecide={(id,value,remarks)=>decision.mutate({id,decision:value,remarks})}/>}</article>)}</div>}{decision.isError&&<ErrorState error={decision.error} label="Decision could not be saved; refresh and review the current request"/>}</section>;
}
