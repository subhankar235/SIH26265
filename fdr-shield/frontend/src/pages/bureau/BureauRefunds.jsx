import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { client } from '../../api/client';
import { useAuthStore } from '../../store/authStore';
import StatusPill from '../../components/common/StatusPill';
import RefundDecisionPanel from '../../components/refund/RefundDecisionPanel';

export default function BureauRefunds() {
  const queryClient = useQueryClient(), user = useAuthStore(s => s.user);
  const { data = [], isLoading, error } = useQuery({ queryKey: ['bureau-refunds'], queryFn: () => client.get('/refunds').then(r => r.data), staleTime: 15_000 });
  const decision = useMutation({
    mutationFn: ({ id, decision: value, remarks }) => client.post(`/refunds/${id}/decision`, { decision: value, remarks }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bureau-refunds'] }),
  });
  return <section><p className="text-sm font-semibold uppercase tracking-wide text-indigo-700">Bureau workspace</p><h1 className="mb-2 mt-1 text-3xl font-bold">Refund decisions</h1><p className="mb-6 text-slate-600">Review release requests for matured, verified deposits.</p>{isLoading?<p>Loading refund requests…</p>:error?<p role="alert" className="text-sm text-red-700">Refund requests could not be loaded.</p>:!data.length?<div className="rounded-xl border bg-white p-10 text-center"><p className="font-semibold">No refund requests yet</p><p className="mt-1 text-sm text-slate-500">Approved release requests will appear here.</p></div>:<div className="space-y-4">{data.map(item=><article key={item.id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Request #{item.id}</p><h2 className="mt-1 font-semibold">FDR #{item.fdr_id}</h2><p className="mt-1 text-sm text-slate-600">{item.remarks || 'No request remarks provided'}</p></div><StatusPill status={item.status}/></div>{item.status==='pending'&&user?.role==='aicte_official'&&<RefundDecisionPanel refund={item} busy={decision.isPending} onDecide={(id,value,remarks)=>decision.mutate({id,decision:value,remarks})}/>}</article>)}</div>}{decision.isError&&<p role="alert" className="mt-4 text-sm text-red-700">Decision could not be saved. Refresh and confirm the request is still pending.</p>}</section>;
}
