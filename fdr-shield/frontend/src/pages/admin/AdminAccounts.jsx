import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { client } from '../../api/client';
import { EmptyState, ErrorState, LoadingState, useToast } from '../../components/common/PageStates';

export default function AdminAccounts({ registrations = false, officialRegistrations = false }) {
  const [error, setError] = useState('');
  const [includeDecided, setIncludeDecided] = useState(false);
  const queryClient = useQueryClient();
  const toast = useToast();
  const registrationPath = officialRegistrations ? '/admin/official-registrations' : '/admin/registrations';
  const queryKey = registrations
    ? [officialRegistrations ? 'admin-official-registrations' : 'admin-registrations', includeDecided]
    : ['admin-users'];

  const query = useQuery({
    queryKey,
    queryFn: () => registrations
      ? client.get(registrationPath, {
          params: includeDecided ? { include_decided: true } : undefined,
        }).then(response => response.data)
      : client.get('/admin/users').then(response => response.data),
  });

  const create = useMutation({
    mutationFn: body => client.post('/admin/users', body),
    onSuccess: () => {
      setError('');
      toast('Invitation created.');
      queryClient.invalidateQueries({ queryKey: ['admin-users'] });
    },
  });

  const action = useMutation({
    mutationFn: async ({ id, kind, decision, reason, body }) => {
      if (kind === 'registration-decision') {
        const resource = officialRegistrations ? 'official-registrations' : 'registrations';
        const suffix = decision === 'override' ? 'override' : decision;
        const routeDecision = decision === 'override' ? body.decision : decision;
        const payload = decision === 'override' ? body : { reason };
        return client.post(`/admin/${resource}/${id}/${suffix}`, { ...payload, decision: routeDecision });
      }
      return client.post(`/admin/users/${id}/${kind}`, body || {});
    },
    onSuccess: () => {
      toast('Account action completed.');
      queryClient.invalidateQueries({ queryKey: registrations ? [queryKey[0]] : ['admin-users'] });
    },
  });

  const updateRole = useMutation({
    mutationFn: ({ id, role, institution_id }) => client.patch(`/admin/users/${id}`, { role, institution_id }),
    onSuccess: () => {
      toast('Role assignment updated.');
      queryClient.invalidateQueries({ queryKey: ['admin-users'] });
    },
  });

  async function submit(event) {
    event.preventDefault();
    setError('');
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form).entries());
    data.institution_id = data.institution_id ? Number(data.institution_id) : null;
    try {
      await create.mutateAsync(data);
      form.reset();
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not invite this account.');
    }
  }

  function decide(row, decision, override = false) {
    const reason = window.prompt(override
      ? `Reason for Super Admin override of ${row.email}`
      : `Reason for ${decision}ing ${row.email}`);
    if (!reason || reason.trim().length < 4) return;
    if (override) {
      action.mutate({ id: row.id, kind: 'registration-decision', decision: 'override',
        body: { decision, reason: reason.trim() } });
    } else {
      action.mutate({ id: row.id, kind: 'registration-decision', decision, reason: reason.trim() });
    }
  }

  const pageTitle = officialRegistrations ? 'AICTE Official applications'
    : registrations ? 'Institution applications' : 'User accounts';

  return <section>
    <p className="text-sm font-semibold uppercase tracking-wide text-indigo-700">Super Admin portal</p>
    <h1 className="mb-2 mt-1 text-3xl font-bold">{pageTitle}</h1>
    {registrations && <>
      <p className="text-sm text-slate-600">Verified applications await approval. Previous decisions can be overridden by a Super Admin.</p>
      <label className="my-4 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={includeDecided} onChange={event => setIncludeDecided(event.target.checked)}/>
        Include previously decided applications
      </label>
    </>}

    {!registrations && <form onSubmit={submit} className="my-6 grid gap-3 rounded-xl border bg-white p-5 sm:grid-cols-2">
      <h2 className="font-semibold sm:col-span-2">Invite account</h2>
      <label className="text-sm">Full name<input name="full_name" required minLength="2" className="mt-1 w-full rounded border p-2"/></label>
      <label className="text-sm">Email<input name="email" type="email" required className="mt-1 w-full rounded border p-2"/></label>
      <label className="text-sm">Role<select name="role" className="mt-1 w-full rounded border p-2">
        <option value="aicte_official">AICTE Official</option><option value="institution">Institution applicant</option>
        <option value="admin">Super Admin</option>
      </select></label>
      <label className="text-sm">Institution ID (required for institution user)<input name="institution_id" type="number" min="1" className="mt-1 w-full rounded border p-2"/></label>
      {error && <p role="alert" className="text-red-700 sm:col-span-2">{error}</p>}
      <button disabled={create.isPending} className="rounded-lg bg-indigo-950 p-3 font-semibold text-white disabled:opacity-60 sm:col-span-2">
        {create.isPending ? 'Sending invite…' : 'Create invitation'}
      </button>
    </form>}

    {query.isLoading ? <LoadingState label="Loading applications"/>
      : query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()}/>
      : !query.data?.length ? <EmptyState title={`No ${includeDecided ? '' : 'pending '}${officialRegistrations ? 'AICTE Official' : registrations ? 'Institution' : 'user'} records`}/>
      : <div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full min-w-[760px] text-left text-sm">
        <thead className="bg-slate-50"><tr>{['Name / Email','Role','Institution','Status','Actions'].map(label => <th className="p-3" key={label}>{label}</th>)}</tr></thead>
        <tbody>{query.data.map(row => <tr className="border-t" key={row.id}>
          <td className="p-3">{row.full_name}<br/><span className="text-slate-500">{row.email}</span></td>
          <td className="p-3">{row.role === 'admin' ? 'Super Admin' : row.role.replaceAll('_', ' ')}</td>
          <td className="p-3">{row.institution_id ?? '—'}</td>
          <td className="p-3">{row.status === 'pending_email_verify' ? 'pending approval' : row.status}</td>
          <td className="p-3"><div className="flex flex-wrap gap-2">
            {registrations && ['pending_approval', 'pending_email_verify'].includes(row.status) && <>
              <button disabled={action.isPending} onClick={() => decide(row, 'approve')} className="rounded bg-green-100 px-2 py-1">Approve</button>
              <button disabled={action.isPending} onClick={() => decide(row, 'reject')} className="rounded bg-red-100 px-2 py-1">Reject</button>
            </>}
            {registrations && includeDecided && ['active','rejected','disabled'].includes(row.status) && <>
              <button disabled={action.isPending} onClick={() => decide(row, 'approve', true)} className="rounded bg-green-100 px-2 py-1">Override · Approve</button>
              <button disabled={action.isPending} onClick={() => decide(row, 'reject', true)} className="rounded bg-red-100 px-2 py-1">Override · Reject</button>
            </>}
            {!registrations && <>
              {row.status === 'active'
                ? <><button disabled={action.isPending} onClick={() => action.mutate({id:row.id,kind:'disable'})} className="rounded border px-2 py-1">Disable</button><button disabled={action.isPending} onClick={() => action.mutate({id:row.id,kind:'suspend'})} className="rounded border px-2 py-1">Suspend</button></>
                : ['disabled','suspended'].includes(row.status) && <button disabled={action.isPending} onClick={() => action.mutate({id:row.id,kind:'enable'})} className="rounded border px-2 py-1">Enable</button>}
              {row.status === 'locked' && <button disabled={action.isPending} onClick={() => action.mutate({id:row.id,kind:'unlock'})} className="rounded border px-2 py-1">Unlock</button>}
              <button disabled={action.isPending} onClick={() => action.mutate({id:row.id,kind:'reset-password'})} className="rounded border px-2 py-1">Send reset link</button>
              <button disabled={action.isPending} onClick={() => action.mutate({id:row.id,kind:'revoke-sessions'})} className="rounded border px-2 py-1">Revoke sessions</button>
              <button disabled={updateRole.isPending} onClick={() => {
                const next = window.prompt('Role: institution, aicte_official, or admin', row.role);
                if (next && ['institution','aicte_official','admin'].includes(next)) updateRole.mutate({id:row.id,role:next,institution_id:row.institution_id});
              }} className="rounded border px-2 py-1">Change role</button>
            </>}
          </div></td>
        </tr>)}</tbody>
      </table></div>}
    {(action.isError || updateRole.isError) && <ErrorState error={action.error || updateRole.error} label="Account action failed"/>}
  </section>;
}
