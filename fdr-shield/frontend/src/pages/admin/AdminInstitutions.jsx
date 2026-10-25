import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { client } from '../../api/client';
import { EmptyState,ErrorState,LoadingState,useToast } from '../../components/common/PageStates';

export default function AdminInstitutions() {
  const [error, setError] = useState(''), queryClient = useQueryClient(),toast=useToast();
  const query = useQuery({ queryKey: ['admin-institutions'], queryFn: () => client.get('/institutions').then(r => r.data) });
  const create = useMutation({ mutationFn: body => client.post('/institutions', body), onSuccess: () => {
    setError(''); toast('Institution created and invitation queued.'); queryClient.invalidateQueries({ queryKey: ['admin-institutions'] });
  }});
  async function submit(e) {
    e.preventDefault(); const form=e.currentTarget, body=Object.fromEntries(new FormData(form).entries());
    try { await create.mutateAsync(body); form.reset(); }
    catch (x) { setError(x.response?.data?.detail || 'Could not create institution or invitation.'); }
  }
  return <section><p className="text-sm font-semibold uppercase tracking-wide text-indigo-700">Admin portal</p><h1 className="mb-2 mt-1 text-3xl font-bold">Institution records</h1><p className="mb-6 text-slate-600">Creating an institution also emails a one-time invitation to its initial account holder.</p>
    <form onSubmit={submit} className="mb-6 grid gap-3 rounded-xl border bg-white p-5 sm:grid-cols-2">
      { [['aicte_id','AICTE institution ID'],['name','Institution name'],['state','State'],['head_name','Contact person'],['contact_email','Contact email'],['contact_phone','Contact phone']].map(([name,label])=><label className="text-sm" key={name}>{label}<input name={name} type={name==='contact_email'?'email':'text'} required className="mt-1 w-full rounded border p-2.5"/></label>)}
      {error&&<p role="alert" className="text-red-700 sm:col-span-2">{error}</p>}
      <button disabled={create.isPending} className="rounded-lg bg-indigo-950 p-3 font-semibold text-white sm:col-span-2">{create.isPending?'Creating…':'Create institution and invite'}</button>
    </form>
     {query.isLoading?<LoadingState label="Loading institutions"/>:query.isError?<ErrorState error={query.error} onRetry={()=>query.refetch()} label="Could not load institutions"/>:!query.data?.length?<EmptyState title="No institutions registered">Create an institution above to send its first account invitation.</EmptyState>:<div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{query.data.map(row=><article key={row.id} className="rounded-xl border bg-white p-5"><p className="text-xs font-semibold text-indigo-700">{row.aicte_id}</p><h2 className="mt-1 text-lg font-semibold">{row.name}</h2><p className="mt-1 text-sm text-slate-500">{row.state} · {row.head_name}</p><p className="mt-4 text-sm">{row.contact_email}</p></article>)}</div>}
  </section>;
}
