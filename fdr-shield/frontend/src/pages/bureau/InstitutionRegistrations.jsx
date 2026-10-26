import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { client } from '../../api/client';
import { EmptyState, ErrorState, LoadingState, useToast } from '../../components/common/PageStates';

export default function InstitutionRegistrations() {
  const [reasonById, setReasonById] = useState({});
  const queryClient = useQueryClient();
  const toast = useToast();
  const query = useQuery({ queryKey: ['official-institution-registrations'],
    queryFn: () => client.get('/institutions/registrations').then(response => response.data) });
  const decision = useMutation({
    mutationFn: ({ id, decision: choice, reason }) => client.post(`/institutions/registrations/${id}/decision`, {
      decision: choice, reason,
    }),
    onSuccess: (_, variables) => {
      toast(variables.decision === 'approve' ? 'Institution application approved.' : 'Institution application rejected.');
      queryClient.invalidateQueries({ queryKey: ['official-institution-registrations'] });
    },
  });

  function decide(row, choice) {
    const reason = reasonById[row.id]?.trim();
    if (!reason || reason.length < 4) return;
    decision.mutate({ id: row.id, decision: choice, reason });
  }

  return <section>
    <p className="text-sm font-semibold uppercase tracking-wide text-indigo-700">AICTE Official</p>
    <h1 className="mb-2 mt-1 text-3xl font-bold">Institution applications</h1>
    <p className="mb-5 text-slate-600">Review email-verified applications. Super Admin retains direct and override authority.</p>
    {query.isLoading ? <LoadingState label="Loading applications"/>
      : query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()}/>
      : !query.data?.length ? <EmptyState title="No applications awaiting review">New verified Institution applications will appear here.</EmptyState>
      : <div className="space-y-4">{query.data.map(row => <article key={row.id} className="rounded-xl border bg-white p-5">
        <div className="flex flex-wrap justify-between gap-2"><div><h2 className="font-semibold">{row.full_name}</h2><p className="text-sm text-slate-600">{row.email} · Institution #{row.institution_id}</p></div><span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold">{row.status}</span></div>
        <label className="mt-4 block text-sm">Decision rationale<textarea value={reasonById[row.id] || ''} onChange={event => setReasonById(values => ({...values,[row.id]:event.target.value}))} minLength={4} maxLength={1000} required className="mt-1 w-full rounded-lg border p-3" placeholder="Record the reason for this decision"/></label>
        <div className="mt-3 flex gap-2"><button disabled={decision.isPending || (reasonById[row.id] || '').trim().length < 4} onClick={() => decide(row,'approve')} className="rounded-lg bg-emerald-100 px-4 py-2 font-semibold text-emerald-900 disabled:opacity-50">Approve</button><button disabled={decision.isPending || (reasonById[row.id] || '').trim().length < 4} onClick={() => decide(row,'reject')} className="rounded-lg bg-red-100 px-4 py-2 font-semibold text-red-900 disabled:opacity-50">Reject</button></div>
      </article>)}</div>}
    {decision.isError && <ErrorState error={decision.error} label="Application decision failed"/>}
  </section>;
}
